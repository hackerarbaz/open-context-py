import json
import requests
import hashlib
from time import sleep
from rdflib import Graph, URIRef, Literal, Namespace
from rdflib.namespace import RDF, RDFS, SKOS, OWL
from django.conf import settings
from django.db import connection
from django.db import models
from django.db.models import Q
from django.core.cache import caches
from django.utils.http import urlquote, quote_plus, urlquote_plus
from opencontext_py.libs.general import LastUpdatedOrderedDict
from opencontext_py.libs.generalapi import GeneralAPI
from opencontext_py.apps.entities.uri.models import URImanagement
from opencontext_py.apps.ldata.pelagios.models import PelagiosData


class PelagiosGraph():
    """ Uses the PelagiosData object to 
        to make Pelagios compliant open annotations
        
from opencontext_py.apps.ldata.pelagios.graph import PelagiosGraph
pelagios = PelagiosGraph()
pelagios.project_uuids = ['3']
pelagios.test_limit = 10
pelagios.make_graph()
pelagios.g.serialize(format='turtle')
    """
    NAMESPACES = {
        'cnt': 'http://www.w3.org/2011/content#',
        'dcterms': 'http://purl.org/dc/terms/',
        'foaf': 'http://xmlns.com/foaf/0.1/',
        'oa': 'http://www.w3.org/ns/oa#',
        'pelagios': 'http://pelagios.github.io/vocab/terms#',
        'relations': 'http://pelagios.github.io/vocab/relations#',
        # 'xsd': 'http://www.w3.org/2001/XMLSchema',
        'oc-gen': 'http://opencontext.org/vocabularies/oc-general/'
    }
    
    def __init__(self):
        self.data_obj = PelagiosData()
        self.project_uuids = []
        self.test_limit = None
        self.g = None
        self.prep_graph()
        self.base_uri = settings.CANONICAL_HOST + '/pelagios/data/'
        self.anno_index = 0
        self.request = False
        self.refresh_cache = False
        self.print_caching = False
        self.cache_ok = True
        self.cache_timeout = None  # None means forever
    
    def prep_graph(self):
        """ prepares a graph for Pelagios """
        self.g = Graph()
        for prefix, ns_uri in self.NAMESPACES.items():
            ns = Namespace(ns_uri)
            self.g.bind(prefix, ns)
    
    def make_graph(self):
        associated_uris = []
        self.get_db_data()
        if len(self.data_obj.oa_items) > 0:
            for uuid, oa_item in self.data_obj.oa_items.items():
                if oa_item.is_valid and len(oa_item.gazetteer_uris) > 0:
                    # only make annotations if the item is valid and actually has
                    # gazetteer uris
                    self.make_add_triple(oa_item.uri,
                                         RDF.type,
                                         'pelagios:AnnotatedThing')
                    self.make_add_triple(oa_item.uri,
                                         self.make_full_uri('dcterms', 'title'),
                                         None,
                                         oa_item.title)
                    self.make_add_triple(oa_item.uri,
                                         self.make_full_uri('foaf', 'homepage'),
                                         oa_item.uri)
                    if isinstance(oa_item.description, str):
                        # add description
                        self.make_add_triple(oa_item.uri,
                                             self.make_full_uri('dcterms', 'description'),
                                             None,
                                             oa_item.description)
                    # add language assertion
                    self.make_add_triple(oa_item.uri,
                                         self.make_full_uri('dcterms', 'language'),
                                         None,
                                         settings.LANGUAGE_CODE)
                    # add assertion about part of a project
                    if oa_item.uri != oa_item.project_uri:
                        self.make_add_triple(oa_item.uri,
                                             self.make_full_uri('dcterms', 'isPartOf'),
                                             oa_item.project_uri)
                    # now add gazetteer annotations to the item
                    base_anno_uri =  self.base_uri + oa_item.manifest.project_uuid
                    base_anno_uri += '/annotations/'
                    self.make_gazetteer_annotations(oa_item.uri,
                                                    oa_item.gazetteer_uris,
                                                    base_anno_uri)
                    # now add related annotations
                    if len(oa_item.associated) > 0:
                        for ass in oa_item.associated:
                            self.make_add_triple(ass['uri'],
                                                 RDF.type,
                                                 'pelagios:AnnotatedThing')
                            self.make_add_triple(ass['uri'],
                                                 self.make_full_uri('dcterms', 'title'),
                                                 None,
                                                 ass['title'])
                            self.make_add_triple(ass['uri'],
                                                 self.make_full_uri('foaf', 'homepage'),
                                                 ass['uri'])
                            self.make_add_triple(ass['uri'],
                                                 self.make_full_uri('dcterms', 'description'),
                                                 None,
                                                 ass['description'])
                            self.make_add_triple(ass['uri'],
                                                 self.make_full_uri('dcterms', 'language'),
                                                 None,
                                                 settings.LANGUAGE_CODE)
                            self.make_add_triple(ass['uri'],
                                                 self.make_full_uri('dcterms', 'relation'),
                                                 oa_item.uri)
                            self.make_gazetteer_annotations(ass['uri'],
                                                            oa_item.gazetteer_uris,
                                                            base_anno_uri)
                            
                                 
    def make_gazetteer_annotations(self, target_uri, gazetteer_uris, base_anno_uri):
        """ makes annotations for a target_uri from from a list of gazetteer_uris """
        for gaz_uri in gazetteer_uris:
            self.anno_index += 1
            anno_uri = base_anno_uri + str(self.anno_index)
            self.make_add_triple(anno_uri,
                                 RDF.type,
                                 self.make_full_uri('oa', 'Annotation'))
            self.make_add_triple(anno_uri,
                                 self.make_full_uri('oa', 'hasTarget'),
                                 target_uri)
            self.make_add_triple(anno_uri,
                                 self.make_full_uri('oa', 'hasBody'),
                                 gaz_uri)
            
                                    
    def make_add_triple(self, sub_uri, pred_uri, obj_uri=None, obj_literal=None):
        """ makes a triple and adds it to the graph """
        act_s = URIRef(sub_uri)
        act_p = URIRef(pred_uri)
        if obj_literal is not None:
            act_o = Literal(obj_literal)
        else:
            act_o = URIRef(obj_uri)
        self.g.add((act_s, act_p, act_o))
    
    def make_full_uri(self, prefix, value):
        """ makes a full uri for a prefix and value """
        if prefix in self.NAMESPACES:
            output = self.NAMESPACES[prefix] + value
        else:
            output = prefix + ':' + value
        return output
            
    def get_db_data(self):
        """ gets gazetteer related items, then
            populates these with manifest objects and context
            paths (for subjects)
        """
        key = self.make_cache_key('pelagios',
                                  '-'.join(self.project_uuids))
        if self.refresh_cache:
            # we forcing a refresh of the cache, not us of cached data
            cache_data_obj = None
        else:
            # check to see if we have a cached version
            cache_data_obj = self.get_cache_object(key)
        if cache_data_obj is None:
            self.data_obj.project_uuids = self.project_uuids
            self.data_obj.test_limit = self.test_limit
            self.data_obj.get_prep_ocitems_rel_gazetteer()
            # now cache the data
            self.save_cache_object(key, self.data_obj)
        else:
            # use the cached data for the data object
            self.data_obj = cache_data_obj
    
    def make_cache_key(self, prefix, identifier):
        """ makes a valid OK cache key """
        return str(prefix) + "-" + str(identifier)
    
    def make_cache_key_hash(self, prefix, identifier):
        """ makes a valid OK cache key """
        hash_obj = hashlib.sha1()
        concat_string = str(prefix) + "-" + str(identifier)
        hash_obj.update(concat_string.encode('utf-8'))
        return hash_obj.hexdigest()

    def get_cache_object(self, key):
        """ gets a cached reddis object """
        try:
            cache = caches['default']
            obj = cache.get(key)
            if self.print_caching:
                print('Cache checked: ' + key)
        except:
            obj = None
            if self.print_caching:
                print('Cache Fail checked: ' + key)
        return obj

    def save_cache_object(self, key, obj):
        """ saves a cached reddis object """
        try:
            cache = caches['default']
            cache.set(key, obj, self.cache_timeout)
            ok = True
            if self.print_caching:
                print('Cache Saved: ' + key)
        except:
            self.cache_ok = False
            ok = False
            if self.print_caching:
                print('Failed to cache: ' + key)
        return ok
    