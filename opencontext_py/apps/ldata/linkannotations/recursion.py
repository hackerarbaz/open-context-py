import hashlib
from django.db import models
from django.db.models import Q
from opencontext_py.apps.ldata.linkannotations.models import LinkAnnotation
from opencontext_py.apps.entities.uri.models import URImanagement
from opencontext_py.apps.entities.entity.models import Entity
from opencontext_py.libs.general import LastUpdatedOrderedDict


class LinkRecursion():
    """
    Does recursive look ups on link annotations, especially to find hierarchies
    """
    def __init__(self):
        self.parent_entities = []

    def get_jsonldish_entity_parents(self, identifier, add_original=True):
        """
        Gets parent concepts for a given URI or UUID identified entity
        returns a list of dictionary objects similar to JSON-LD expectations
        This is useful for faceted search

        If add_original is true, add the original UUID for the entity
        that's the childmost item, at the bottom of the hierarchy
        """
        output = False
        raw_parents = self.get_entity_parents(identifier)
        if(add_original):# 
            output = []  # add the original identifer to the list of parents, at lowest rank
            raw_parents.insert(0, identifier)
        if(len(raw_parents) > 0):
            output = []
            # reverse the order of the list, to make top most concept
            # first
            parents = raw_parents[::-1]
            for par_id in parents:
                ent = Entity()
                found = ent.dereference(par_id)
                if(found):
                    p_item = LastUpdatedOrderedDict()
                    p_item['id'] = ent.uri
                    p_item['slug'] = ent.slug
                    p_item['label'] = ent.label
                    if(ent.data_type is not False):
                        p_item['type'] = ent.data_type
                    else:
                        p_item['type'] = '@id'
                    output.append(p_item)
        return output

    def get_entity_parents(self, identifier):
        """
        Gets parent concepts for a given URI or UUID identified entity
        """
        p_for_superobjs = LinkAnnotation.PREDS_SBJ_IS_SUB_OF_OBJ
        p_for_subobjs = LinkAnnotation.PREDS_SBJ_IS_SUPER_OF_OBJ
        alt_identifier_a = identifier
        alt_identifier_b = identifier
        # a little something to allow searches of either UUIDs or full URIs
        if(':' in identifier):
            alt_identifier_b = URImanagement.convert_prefix_to_full_uri(identifier)
            if(len(identifier) > 8):
                if(identifier[:7] == 'http://' or identifier[:8] == 'https://'):
                    alt_identifier_a = URImanagement.get_uuid_from_oc_uri(identifier)
                    if(alt_identifier_a is False):
                        alt_identifier_a = identifier
                    alt_identifier_b = URImanagement.prefix_common_uri(identifier)
        try:
            # look for superior items in the objects of the assertion
            superobjs_anno = LinkAnnotation.objects.filter(Q(subject=identifier) |
                                                           Q(subject=alt_identifier_a) |
                                                           Q(subject=alt_identifier_b),
                                                           predicate_uri__in=p_for_superobjs)[:1]
            if(len(superobjs_anno) < 1):
                superobjs_anno = False
        except LinkAnnotation.DoesNotExist:
            superobjs_anno = False
        if(superobjs_anno is not False):
            parent_id = superobjs_anno[0].object_uri
            if(parent_id.count('/') > 1):
                oc_uuid = URImanagement.get_uuid_from_oc_uri(parent_id)
                if(oc_uuid is not False):
                    parent_id = oc_uuid
                if(parent_id not in self.parent_entities):
                    self.parent_entities.append(parent_id)
            self.parent_entities = self.get_entity_parents(parent_id)
        try:
            """
            Now look for superior entities in the subject, not the object
            """
            supersubj_anno = LinkAnnotation.objects.filter(Q(object_uri=identifier) |
                                                           Q(object_uri=alt_identifier_a) |
                                                           Q(object_uri=alt_identifier_b),
                                                           predicate_uri__in=p_for_subobjs)[:1]
            if(len(supersubj_anno) < 1):
                supersubj_anno = False
        except LinkAnnotation.DoesNotExist:
            supersubj_anno = False
        if(supersubj_anno is not False):
            parent_id = supersubj_anno[0].subject
            if(parent_id.count('/') > 1):
                oc_uuid = URImanagement.get_uuid_from_oc_uri(parent_id)
                if(oc_uuid is not False):
                    parent_id = oc_uuid
                if(parent_id not in self.parent_entities):
                    self.parent_entities.append(parent_id)
            self.parent_entities = self.get_entity_parents(parent_id)
        return self.parent_entities