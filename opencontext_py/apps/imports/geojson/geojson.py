import os
import re
import json
import codecs
import datetime
from unidecode import unidecode
from dateutil.parser import parse
from collections import OrderedDict
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.template.defaultfilters import slugify
from opencontext_py.libs.general import LastUpdatedOrderedDict
from opencontext_py.apps.ocitems.manifest.models import Manifest
from opencontext_py.apps.ocitems.geospace.models import Geospace
from opencontext_py.apps.ocitems.events.models import Event
from opencontext_py.apps.imports.sources.models import ImportSource
from opencontext_py.apps.imports.fields.models import ImportField
from opencontext_py.apps.imports.records.models import ImportCell
from opencontext_py.apps.imports.records.create import ImportRecords
from opencontext_py.apps.imports.fields.create import ImportFields
from opencontext_py.apps.imports.sources.create import ImportRefineSource


class GeoJSONimport():
    """ Loads GeoJSON files for import

from opencontext_py.apps.imports.geojson.geojson import GeoJSONimport
gimp = GeoJSONimport()
gimp.load_into_importer = True
gimp.project_uuid = '5A6DDB94-70BE-43B4-2D5D-35D983B21515'
gimp.process_features_in_file('giza-geo', 'Features_KKT.geojson')


    """

    def __init__(self):
        self.root_import_dir = settings.STATIC_IMPORTS_ROOT
        self.project_uuid = False
        self.label = False
        self.source_id = False
        self.class_uri = False
        self.load_into_importer = False
        self.round_int_properties = True  # make integer values of numeric properties that are integer values if rounded
        self.feature_count = False
        self.properties = False
        self.property_data_types = {}
        self.fields = False
        self.imp_source_obj = False
        self.import_batch_size = 250
        self.geometry_field_name = 'geojson-geometry'
        self.geometry_field_type = 'geojson'
        self.props_config = [{'prop': 'FeatureNum',
                              'prefix': 'Feat. ',
                              'data_type': 'xsd:integer'}]

    def get_props_from_features(self, features):
        """ gets a list of all properties used with the features """
        self.properties = []
        self.feature_count = len(features)
        for feature in features:
            if 'properties' in feature:
                props = feature['properties']
                for prop_key, val in props.items():
                    if prop_key not in self.properties:
                        self.properties.append(prop_key)

    def guess_properties_data_types(self, features):
        """ guesses the property data-types, especially
            important to round decimal values to integers
            to enable use of consident identifiers
        """
        irs = ImportRefineSource()
        property_data_types = {}
        prop_types = ['xsd:boolean',
                      'xsd:integer',
                      'xsd:double',
                      'xsd:date',
                      'other']
        property_data_types = {}
        keys = []
        for prop_key in self.properties:
            act_types = {}
            for prop_type in prop_types:
                act_types[prop_type] = 0
            i = 0
            for feature in features:
                i += 1
                if 'properties' in feature:
                    if prop_key in feature['properties']:
                        val = feature['properties'][prop_key]
                        if val is not None:
                            val_data_type = irs.guess_record_data_type(val)
                            if val_data_type is not False:
                                if val_data_type in act_types:
                                    act_types[val_data_type] += 1
                            else:
                                act_types['other'] += 1
            property_data_types[prop_key] = act_types
        # print(str(property_data_types))
        if self.feature_count > 0:
            main_types = {}
            total_counts = {}
            for prop_key, act_prop_types in property_data_types.items():
                max_value = 0
                total_counts[prop_key] = 0
                main_types['data_type'] = 'other'  # default data_type
                for data_type, count in act_prop_types.items():
                    if isinstance(count, int):
                        total_counts[prop_key] += count
                        if count > max_value:
                            max_value = count
                for data_type, count in act_prop_types.items():
                    if isinstance(count, int) and total_counts[prop_key] > 0:
                        if count == max_value and (count / total_counts[prop_key]) > .95:
                            # more than 95% of one type, so choose it
                            main_types[prop_key] = data_type
            for prop_key in self.properties:
                if prop_key in property_data_types:
                    self.property_data_types[prop_key] = property_data_types[prop_key]
                if prop_key in main_types:
                    self.property_data_types[prop_key]['data_type'] = main_types[prop_key]

    def save_features_import_records(self, features):
        """ Saves import records for a list of features, in batches of
            so as to not screw up database transactions
        """
        output = False
        if self.imp_source_obj is not False:
            ImportCell.objects\
                      .filter(source_id=self.source_id,
                              project_uuid=self.project_uuid)\
                      .delete()
            row_num = 0
            rec_list = []
            for feature in features:
                row_num += 1
                new_recs = self.make_import_records_from_feature(row_num,
                                                                 feature)
                rec_list += new_recs
                if len(rec_list) >= self.import_batch_size:
                    print('About to save ' + str(len(rec_list)) + ' cells')
                    ImportCell.objects.bulk_create(rec_list)
                    rec_list = []
            if len(rec_list) > 0:
                print('Saving LAST ' + str(len(rec_list)) + ' cells')
                ImportCell.objects.bulk_create(rec_list)
            self.imp_source_obj.imp_status = ImportRefineSource.DEFAULT_LOADING_DONE_STATUS
            self.imp_source_obj.save()
            output = True
        return output

    def make_import_records_from_feature(self, row_num, feature):
        """ Saves a feature into the importer with properties as different
            'fields' in the importer
        """
        bulk_list = []
        if 'geometry' in feature:
            f_geo = feature['geometry']
        else:
            f_geo = False
        if 'properties' in feature:
            f_props = feature['properties']
            for prop_key, col_index in self.fields.items():
                record = None
                if prop_key in f_props:
                    record = f_props[prop_key]
                    guessed_data_type = self.get_guessed_prop_data_type(prop_key)
                    record = self.transform_validate_record(guessed_data_type,
                                                            record)
                elif prop_key == self.geometry_field_name:
                    # we have a geojson field
                    record = json.dumps(f_geo,
                                        ensure_ascii=False,
                                        indent=4)
                if record is not None:
                    imp_cell = ImportCell()
                    imp_cell.source_id = self.source_id
                    imp_cell.project_uuid = self.project_uuid
                    imp_cell.row_num = row_num
                    imp_cell.field_num = col_index
                    imp_cell.rec_hash = ImportCell().make_rec_hash(self.project_uuid,
                                                                   str(record))
                    imp_cell.fl_uuid = False
                    imp_cell.l_uuid = False
                    imp_cell.cell_ok = True  # default to Import OK
                    imp_cell.record = str(record)
                    bulk_list.append(imp_cell)
        return bulk_list

    def transform_validate_record(self, data_type, record):
        """ transforms a record so that it conforms
            to a certain data_type,
            also converts None (null) values to blank strings
            finally, trims away blanks
        """
        original = record
        if record is None:
            record = ''
        else:
            if data_type == 'xsd:integer':
                if not isinstance(record, int):
                    try:
                        num_rec = float(record)
                    except:
                        num_rec = False
                    if num_rec is not False:
                        int_rec = round(num_rec)
                        if int_rec == num_rec:
                            record = int(int_rec)
            elif data_type == 'xsd:double':
                if not isinstance(record, float):
                    try:
                        num_rec = float(record)
                    except:
                        num_rec = False
                    if num_rec is not False:
                        record = num_rec
            elif data_type == 'xsd:boolean':
                booleans = {
                    'n': False,
                    'no': False,
                    'none': False,
                    'absent': False,
                    'a': False,
                    'false': False,
                    'f': False,
                    '0': False,
                    'y': True,
                    'yes': True,
                    'present': True,
                    'p': True,
                    'true': True,
                    't': True}
                lc_record = str(record).lower()
                if lc_record in booleans:
                    record = str(booleans[lc_record])
            elif data_type == 'xsd:date':
                try:
                    data_date = parse(record)
                except Exception as e:
                    data_date = False
                if data_date is not False:
                    record = data_date.strftime('%Y-%m-%d')
            else:
                record = str(record)
                record = record.strip()
        return record

    def save_properties_as_import_fields(self):
        """ saves the properties as import fields
        """
        output = False
        if self.imp_source_obj is not False:
            imp_f_create = ImportFields()
            imp_f_create.project_uuid = self.project_uuid
            imp_f_create.source_id = self.source_id
            col_index = 0
            new_fields = []
            self.fields = LastUpdatedOrderedDict()
            # add a field for the geometry. It's not a property, but we need
            # a place to save the data
            self.properties.append(self.geometry_field_name)
            for prop_key in self.properties:
                col_index += 1
                self.fields[prop_key] = col_index
                imp_f = ImportField()
                imp_f.project_uuid = self.project_uuid
                imp_f.source_id = self.source_id
                imp_f.field_num = col_index
                imp_f.is_keycell = False
                imp_f.obs_num = 1
                imp_f.label = prop_key
                imp_f.ref_name = prop_key
                imp_f.ref_orig_name = prop_key
                imp_f.unique_count = 0
                # now add some field metadata based on other fields data in the project
                imp_f = imp_f_create.check_for_updated_field(imp_f,
                                                             prop_key,
                                                             prop_key,
                                                             True)
                # now add a field_data_type based on the guess made on this GeoJSON property
                guessed_data_type = self.get_guessed_prop_data_type(prop_key)
                if guessed_data_type is not False:
                    imp_f.field_data_type = guessed_data_type
                if prop_key == self.geometry_field_name:
                    imp_f.field_data_type = 'xsd:string'
                    imp_f.field_type = self.geometry_field_type
                new_fields.append(imp_f)
            # now delete any old
            ImportField.objects.filter(source_id=self.source_id).delete()
            # now save the new import fields
            for imp_f in new_fields:
                print('Saving field: ' + str(unidecode(imp_f.label)))
                imp_f.save()
            output = True
        return output

    def get_guessed_prop_data_type(self, prop_key):
        """ gets the guessed property data type, if
            determined to be boolean, integer, double, or data
        """
        output = False
        if prop_key in self.property_data_types:
                if 'data_type' in self.property_data_types[prop_key]:
                    if self.property_data_types[prop_key]['data_type'] != 'other':
                        output = self.property_data_types[prop_key]['data_type']
        return output

    def save_import_source(self):
        """ saves the import source object """
        output = False
        if self.properties is not False:
            if self.feature_count > 0 \
               and len(self.properties) > 0:
                # delete a previous record if it exists
                ImportSource.objects\
                            .filter(source_id=self.source_id,
                                    project_uuid=self.project_uuid)\
                            .delete()
                irs = ImportRefineSource()
                imp_s = ImportSource()
                imp_s.source_id = self.source_id
                imp_s.project_uuid = self.project_uuid
                imp_s.label = self.label
                imp_s.field_count = len(self.properties) + 1  # the added 1 is for the geojson field
                imp_s.row_count = self.feature_count
                imp_s.source_type = 'geojson'
                imp_s.is_current = True
                imp_s.imp_status = irs.DEFAULT_LOADING_STATUS
                imp_s.save()
                self.imp_source_obj = imp_s
                output = True
        return output

    def add_feature_to_existing_items(self, feature):
        """ Process a feature to extract geospatial
            object. It will:
            (1) Find the appropriate item in the manifest table
            (2) Adds a record in the geospace table
        """
        if 'properties' in feature:
            props = feature['properties']
            for check_prop in self.props_config:
                if check_prop['prop'] in props:
                    prop_id = str(props[check_prop['prop']])
                    if check_prop['data_type'] == 'xsd:integer':
                        try:
                            num_id = float(prop_id)
                        except:
                            num_id = False
                        if num_id is not False:
                            try:
                                int_id = int(num_id)
                            except:
                                int_id = False
                            if int_id is not False:
                                prop_id = str(int_id)
                    prop_id = check_prop['prefix'] + prop_id
                    print('Checking to find: ' + prop_id)
                    man_objs = Manifest.objects\
                                       .filter(label=prop_id,
                                               project_uuid=self.project_uuid,
                                               class_uri=self.class_uri)[:1]
                    if len(man_objs):
                        uuid = str(man_objs[0].uuid)
                    else:
                        uuid = False
                    if uuid is not False:
                        # found a uuid for this item!
                        print('Found: ' + prop_id + ' is ' + uuid)

    def process_features_in_file(self, act_dir, filename):
        """ Processes a file to extract geojson features
            for processing each feature
        """
        json_obj = self.load_json_file(act_dir, filename)
        if json_obj is not False:
            if 'features' in json_obj:
                if self.load_into_importer:
                    self.get_props_from_features(json_obj['features'])
                    self.guess_properties_data_types(json_obj['features'])
                    self.save_import_source()
                    self.save_properties_as_import_fields()
                    self.save_features_import_records(json_obj['features'])
                else:
                    for feature in json_obj['features']:
                        self.add_feature_to_existing_items(feature)

    def set_check_directory(self, act_dir):
        """ Prepares a directory to find import GeoJSON files """
        output = False
        full_dir = self.root_import_dir + act_dir + '/'
        if os.path.exists(full_dir):
            output = full_dir
        return output

    def load_json_file(self, act_dir, filename):
        """ Loads a file and parse it into a
            json object
        """
        json_obj = False
        dir_file = self.set_check_directory(act_dir) + filename
        if os.path.exists(dir_file):
            self.make_source_id(act_dir, filename)
            fp = open(dir_file, 'r')
            # keep keys in the same order as the original file
            json_obj = json.load(fp, object_pairs_hook=OrderedDict)
        return json_obj

    def make_source_id(self, act_dir, filename):
        """ makes a source_id by sluggifying the act_dir and filename """
        dir_file = act_dir + ' ' + filename
        dir_file = dir_file.replace('_', ' ')
        self.label = dir_file
        dir_file = dir_file.replace('.', '-')
        raw_slug = slugify(unidecode(dir_file[:40]))
        if raw_slug[0] == '-':
            raw_slug = raw_slug[1:]  # slugs don't end with dashes
        if raw_slug[-1:] == '-':
            raw_slug = raw_slug[:-1]  # slugs don't end with dashes
        raw_slug = re.sub(r'([-]){2,}', r'-', raw_slug)  # slugs can't have more than 1 dash characters
        self.source_id = 'geojson:' + raw_slug
        return self.source_id
