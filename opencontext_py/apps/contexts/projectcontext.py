from django.db import connection
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.core.cache import caches
from opencontext_py.libs.rootpath import RootPath
from opencontext_py.libs.general import LastUpdatedOrderedDict
from opencontext_py.apps.contexts.models import GeneralContext
from opencontext_py.apps.entities.uri.models import URImanagement
from opencontext_py.apps.entities.entity.models import Entity
from opencontext_py.apps.ocitems.manifest.models import Manifest
from opencontext_py.apps.ocitems.projects.permissions import ProjectPermissions
from opencontext_py.apps.ocitems.projects.models import Project
from opencontext_py.apps.ocitems.persons.models import Person
from opencontext_py.apps.ocitems.assertions.models import Assertion
from opencontext_py.apps.ocitems.predicates.models import Predicate
from opencontext_py.apps.ocitems.strings.models import OCstring
from opencontext_py.apps.ldata.linkannotations.models import LinkAnnotation
from opencontext_py.apps.ldata.linkentities.models import LinkEntity
from opencontext_py.apps.ocitems.queries.security import SecurityForQuery


class ProjectContext():
    """
    Contexts documenting the predicates, types, and their
    annotations used in a project
    """

    def __init__(self, uuid=None, request=None):
        self.id_href = True  # use the local href as the Context's ID
        self.uuid = uuid
        rp = RootPath()
        self.base_url = rp.get_baseurl()
        self.manifest = False
        self.project_obj = False
        self.edit_status = 0
        self.edit_permitted = False
        self.view_permitted = True
        self.assertion_hashes = False
        self.id = False
        self.href = False
        self.cannonical_href = False
        self.json_ld = False
        self.errors = []
        self.pred_sql_dict_list = None
        self.most_recent_date = None
        if uuid is not None:
            self.dereference_uuid_or_slug(uuid)
            self.set_uri_urls(self.uuid)
            if request is not None:
                self.check_permissions(request)

    def make_context_json_ld(self):
        """ makes the context JSON-LD """
        if self.manifest is not False:
            self.json_ld = LastUpdatedOrderedDict()
            gen_context = GeneralContext()
            context = gen_context.context
            context = self.add_project_predicates_to_context(context)
            self.json_ld['@context'] = context
            self.json_ld['id'] = self.id
            self.json_ld['label'] = 'Context and Standards Annotations for ' + self.manifest.label
            graph = []
            graph = self.add_project_predicates_and_annotations_to_graph(graph)
            graph = self.add_project_types_with_annotations_to_graph(graph)
            self.json_ld['@graph'] = graph
        else:
            self.json_ld = False
        return self.json_ld

    def add_project_predicates_to_context(self, context):
        """ adds project predicates to the context """
        pred_sql_dict_list = self.get_working_project_predicates()
        if isinstance(pred_sql_dict_list, list):
            for sql_dict in pred_sql_dict_list:
                act_pred = LastUpdatedOrderedDict()
                if sql_dict['data_type'] == 'id':
                    act_pred['type'] = '@id'
                else:
                    act_pred['type'] = sql_dict['data_type']
                context_key = 'oc-pred:' + sql_dict['slug']
                context[context_key] = act_pred
        return context

    def add_project_predicates_and_annotations_to_graph(self, graph):
        """ gets the project predicates and their
            annotations with database calls
        """
        pred_sql_dict_list = self.get_working_project_predicates()
        la_preds = self.get_link_annotations_for_preds(pred_sql_dict_list)
        if isinstance(pred_sql_dict_list, list):
            for sql_dict in pred_sql_dict_list:
                act_pred = LastUpdatedOrderedDict()
                act_pred['@id'] = 'oc-pred:' + sql_dict['slug']
                act_pred['owl:sameAs'] = URImanagement.make_oc_uri(sql_dict['predicate_uuid'],
                                                                   'predicates')
                act_pred['label'] = sql_dict['label']
                act_pred['uuid'] = sql_dict['predicate_uuid']
                act_pred['slug'] = sql_dict['slug']
                if isinstance(sql_dict['class_uri'], str):
                    if len(sql_dict['class_uri']) > 0:
                        act_pred['oc-gen:predType'] = sql_dict['class_uri']
                pred_found = False
                for la_pred in la_preds:
                    if la_pred.subject == sql_dict['predicate_uuid']:
                        pred_found = True
                        # prefix common URIs for the predicate of the link annotation
                        la_pred_uri = URImanagement.prefix_common_uri(la_pred.predicate_uri)
                        if la_pred_uri not in act_pred:
                            act_pred[la_pred_uri] = []
                        la_object_item = self.make_object_dict_item(la_pred.object_uri)
                        act_pred[la_pred_uri].append(la_object_item)
                    else:
                        if pred_found:
                            # because this list is sorted by la_pred.subject, we're done
                            # finding any more annotations on act_pred item
                            break
                graph.append(act_pred)
        return graph

    def get_working_project_predicates(self):
        """ gets project predicates from the assertions table.
            this uses a raw sql query to query using a somewhat
            complicated set of joins.
            It's not much of a security risk, since the only
            parameter passed to the query is from the manifest object
            which has to be OK and not a SQL injection
        """
        output = None
        if self.manifest is not False and self.pred_sql_dict_list is None:
            # security protection
            not_in_list = [
                Assertion.PREDICATES_CONTAINS,
                Assertion.PREDICATES_LINK,
                Assertion.PREDICATES_NOTE
            ]
            not_in_sql = ''
            for not_in in not_in_list:
                if len(not_in_sql) > 0:
                    not_in_sql += ' AND '
                not_in_sql += ' ass.predicate_uuid != \'' + not_in + '\' '
            not_in_sql = '(' + not_in_sql + ')'
            query = ('SELECT ass.predicate_uuid AS predicate_uuid, '
                     'm.label AS label, '
                     'm.slug AS slug, '
                     'm.class_uri AS class_uri, '
                     'p.data_type AS data_type, '
                     'm.revised AS updated '
                     'FROM oc_assertions AS ass '
                     'LEFT JOIN oc_manifest AS m ON ass.predicate_uuid = m.uuid '
                     'LEFT JOIN oc_predicates AS p ON ass.predicate_uuid = p.uuid '
                     'WHERE ass.project_uuid = (%s) AND ' + not_in_sql + ' '
                     'GROUP BY ass.predicate_uuid, '
                     'm.label, '
                     'm.slug, '
                     'm.class_uri, '
                     'm.revised, '
                     'p.data_type '
                     'ORDER BY p.data_type, m.slug, m.class_uri; ')
            cursor = connection.cursor()
            cursor.execute(query, [self.manifest.uuid])
            rows = self.dictfetchall(cursor)
            output = rows
            self.pred_sql_dict_list = output
        return self.pred_sql_dict_list

    def get_link_annotations_for_preds(self, pred_sql_dict_list):
        """ gets link annotations for predicates """
        la_preds = []
        if isinstance(pred_sql_dict_list, list):
            pred_uuids = []
            for sql_dict in pred_sql_dict_list:
                pred_uuids.append(sql_dict['predicate_uuid'])
            la_preds = LinkAnnotation.objects\
                                     .filter(subject__in=pred_uuids)\
                                     .order_by('subject', 'predicate_uri', 'sort')
        return la_preds

    def add_project_types_with_annotations_to_graph(self, graph):
        """ adds project types that have annotations """
        type_sql_dict_list = self.get_working_project_types()
        if isinstance(type_sql_dict_list, list):
            # consolidate things so a given type is given once in the list
            # of a graph. To do so, we first put everything in a all_types
            # dict
            all_types = LastUpdatedOrderedDict()
            for sql_dict in type_sql_dict_list:
                type_uri = URImanagement.make_oc_uri(sql_dict['type_uuid'],
                                                              'types')
                if type_uri not in all_types:
                    act_type = LastUpdatedOrderedDict()
                    act_type['@id'] = type_uri 
                    act_type['label'] = sql_dict['type_label']
                    act_type['owl:sameAs'] = URImanagement.make_oc_uri(sql_dict['type_slug'],
                                                                       'types')
                    act_type['uuid'] = sql_dict['type_uuid']
                    act_type['slug'] = sql_dict['type_slug']
                else:
                    act_type = all_types[type_uri]
                la_pred_uri = URImanagement.prefix_common_uri(sql_dict['predicate_uri'])
                if la_pred_uri not in act_type:
                    act_type[la_pred_uri] = []
                la_object_item = self.make_object_dict_item(sql_dict['object_uri'])
                act_type[la_pred_uri].append(la_object_item)
                all_types[type_uri] = act_type
            for type_uri, act_type in all_types.items():
                graph.append(act_type)
        return graph

    def get_working_project_types(self):
        """ gets project types that have linked data annotations.
            This uses a raw sql query to query using a somewhat
            complicated set of joins.
            It's not much of a security risk, since the only
            parameter passed to the query is from the manifest object
            which has to be OK and not a SQL injection
        """
        output = None
        if self.manifest is not False:
            query = ('SELECT la.subject AS type_uuid, '
                     'la.predicate_uri AS predicate_uri, '
                     'la.object_uri AS object_uri, '
                     'm.label AS type_label, '
                     'm.slug AS type_slug '
                     'FROM link_annotations AS la '
                     'LEFT JOIN oc_manifest AS m ON la.subject = m.uuid '
                     'JOIN oc_assertions AS ass '
                     'ON ( la.subject = ass.object_uuid ) '
                     'WHERE la.subject_type = \'types\' AND ass.project_uuid = (%s) '
                     'GROUP BY la.subject, '
                     'la.predicate_uri, '
                     'la.object_uri, '
                     'm.label, '
                     'm.slug '
                     'ORDER BY la.object_uri; ')
            cursor = connection.cursor()
            cursor.execute(query, [self.manifest.uuid])
            rows = self.dictfetchall(cursor)
            output = rows
        return output

    def dictfetchall(self, cursor):
        """ Return all rows from a cursor as a dict """
        columns = [col[0] for col in cursor.description]
        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    def make_object_dict_item(self, identifier):
        """ makes a dict item for the object of a predicate """
        item = LastUpdatedOrderedDict()
        item['id'] = identifier
        item['label'] = False
        ent = Entity()
        found = ent.dereference(identifier)
        if found is False:
            found = ent.dereference(identifier, identifier)
        if found:
            item['label'] = ent.label
            item['slug'] = ent.slug
        return item

    def dereference_uuid_or_slug(self, uuid_or_slug):
        """ dereferences the uuid to make sure it is a project """
        man_list = Manifest.objects\
                           .filter(Q(uuid=uuid_or_slug) | Q(slug=uuid_or_slug),
                                   item_type='projects')[:1]
        if len(man_list) > 0:
            self.manifest = man_list[0]
            self.uuid = self.manifest.uuid
        else:
            self.manifest = False
            self.errors.append('Item ' + uuid_or_slug + ' not in manifest')
        if self.manifest is not False:
            try:
                self.project_obj = Project.objects.get(uuid=self.manifest.uuid)
                self.edit_status = self.project_obj.edit_status
            except Project.DoesNotExist:
                self.project_obj = False
                self.edit_status = 0

    def check_permissions(self, request):
        """ checks permissions """
        if request is not None and self.manifest is not False:
            # check to make sure edit permissions OK
            pp = ProjectPermissions(self.manifest.project_uuid)
            self.edit_permitted = pp.edit_allowed(request)
            self.view_permitted = pp.view_allowed(request)

    def set_uri_urls(self, uuid):
        """ sets the uris and urls for this context resource """
        if self.uuid is None:
            self.uuid = uuid
        self.href = self.base_url + '/contexts/projects/' \
            + str(self.uuid) + '.json'  # URL for this
        self.cannonical_href = settings.CANONICAL_HOST + '/contexts/projects/' \
            + str(self.uuid) + '.json'  # URI for main host
        if self.id_href:
            self.id = self.href
        else:
            self.id = self.cannonical_href

