import os
import json
import codecs
from django.db import models
from django.conf import settings
from django.core import serializers
from opencontext_py.apps.ocitems.manifest.models import Manifest
from opencontext_py.apps.ocitems.assertions.models import Assertion
from opencontext_py.apps.ocitems.events.models import Event
from opencontext_py.apps.ocitems.geospace.models import Geospace
from opencontext_py.apps.ocitems.obsmetadata.models import ObsMetadata
from opencontext_py.apps.ocitems.predicates.models import Predicate
from opencontext_py.apps.ocitems.octypes.models import OCtype
from opencontext_py.apps.ocitems.strings.models import OCstring
from opencontext_py.apps.ocitems.subjects.models import Subject
from opencontext_py.apps.ocitems.mediafiles.models import Mediafile
from opencontext_py.apps.ocitems.documents.models import OCdocument
from opencontext_py.apps.ocitems.persons.models import Person
from opencontext_py.apps.ocitems.projects.models import Project
from opencontext_py.apps.ocitems.identifiers.models import StableIdentifer
from opencontext_py.apps.ldata.linkannotations.models import LinkAnnotation
from opencontext_py.apps.ldata.linkentities.models import LinkEntity
from opencontext_py.apps.exports.expfields.models import ExpField
from opencontext_py.apps.exports.exprecords.models import ExpCell
from opencontext_py.apps.exports.exptables.models import ExpTable
from opencontext_py.apps.edit.inputs.profiles.models import InputProfile
from opencontext_py.apps.edit.inputs.fieldgroups.models import InputFieldGroup
from opencontext_py.apps.edit.inputs.inputrelations.models import InputRelation
from opencontext_py.apps.edit.inputs.inputfields.models import InputField
from opencontext_py.apps.edit.inputs.rules.models import InputRule


# Reads Serialized JSON from the Exporter
class ImportSerizializedJSON():
    """

from opencontext_py.apps.Imports.serialization.models import ImportSerizializedJSON
sj = SerizializeJSON()
sj.dump_serialized_data("3885b0b6-2ba8-4d19-b597-7f445367c5c0")

    """
    def __init__(self):
        self.root_import_dir = settings.STATIC_IMPORTS_ROOT

    def get_directory_files(self, act_dir):
        """ Gets a list of files from a directory """
        files = False
        full_dir = self.root_import_dir + act_dir + '/'
        if os.path.exists(full_dir):
            for dirpath, dirnames, filenames in os.walk(full_dir):
                files = filenames
        return files

    def load_json_file(self, dir_file):
        """ Loads a file and parse it into a
            json object
        """
        json_obj = False
        if os.path.exists(dir_file):
            fp = open(dir_file, 'r')
            json_obj = json.load(fp)
        return json_obj
