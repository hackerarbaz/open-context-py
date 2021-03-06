import json
from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpResponse, Http404
from django.template import RequestContext, loader
from opencontext_py.libs.rootpath import RootPath
from opencontext_py.libs.solrconnection import SolrConnection
from opencontext_py.libs.general import LastUpdatedOrderedDict
from opencontext_py.libs.requestnegotiation import RequestNegotiation
from opencontext_py.libs.memorycache import MemoryCache
from opencontext_py.libs.databasecache import DatabaseCache
from opencontext_py.apps.searcher.solrsearcher.models import SolrSearch
from opencontext_py.apps.searcher.solrsearcher.makejsonld import MakeJsonLd
from opencontext_py.apps.searcher.solrsearcher.filterlinks import FilterLinks
from opencontext_py.apps.searcher.solrsearcher.templating import SearchTemplate
from opencontext_py.apps.searcher.solrsearcher.requestdict import RequestDict
from opencontext_py.apps.searcher.solrsearcher.reconciliation import Reconciliation
from opencontext_py.apps.searcher.solrsearcher.projtemplating import ProjectAugment
from django.views.decorators.cache import cache_control
from django.views.decorators.cache import never_cache


def index(request, spatial_context=None):
    return HttpResponse("Hello, world. You're at the search index.")


def sets_view(request, spatial_context=''):
    """ redirects requests from the legacy site 'sets'
        to the subjects-search view

        We can add URL parameter mappings to this later
        so that old url parameters can be mapped to the
        current parameters
    """
    url = request.get_full_path()
    new_url = url.replace('/sets/', '/subjects-search/')
    param_suffix = ''
    if '?' in url:
        url_ex = url.split('?')
        param_suffix = '?' + url_ex[1]
    return redirect(new_url, permanent=True)


def lightbox_view(request, spatial_context=''):
    """ redirects requests from the legacy site 'lightbox'
        to the media-search view

        We can add URL parameter mappings to this later
        so that old url parameters can be mapped to the
        current parameters
    """
    url = request.get_full_path()
    new_url = url.replace('/lightbox/', '/media-search/')
    param_suffix = ''
    if '?' in url:
        url_ex = url.split('?')
        param_suffix = '?' + url_ex[1]
    return redirect(new_url, permanent=True)


# @cache_control(no_cache=True)
# @never_cache
def html_view(request, spatial_context=None):
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    rp = RootPath()
    base_url = rp.get_baseurl()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        # looks like an abusive SQL injection request
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        cache_control(no_cache=True)
        return redirect('/search/', permanent=False)
    else:
        # url and json_url neeed for view templating
        url = request.get_full_path()
        if 'http://' not in url \
           and 'https://' not in url:
            url = base_url + url
        if '?' in url:
            json_url = url.replace('?', '.json?')
        else:
            json_url = url + '.json'
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('search',
                                            request_dict_json)
        # print('Cache key: ' + cache_key)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.do_bot_limit = rd.do_bot_limit  # Toggle limits on facets for bots
            solr_s.mem_cache_obj = mem_cache_obj
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                mem_cache_obj = solr_s.mem_cache_obj  # reused cached memory items
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/search/'
                # share entities already looked up. Saves database queries
                m_json_ld.mem_cache_obj = mem_cache_obj
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('text/html')
            req_neg.supported_types = ['application/json',
                                       'application/ld+json',
                                       'application/vnd.geo+json']
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if 'json' in req_neg.use_response_type:
                # content negotiation requested JSON or JSON-LD
                recon_obj = Reconciliation()
                json_ld = recon_obj.process(request.GET,
                                            json_ld)
                return HttpResponse(json.dumps(json_ld,
                                    ensure_ascii=False, indent=4),
                                    content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # now make the JSON-LD into an object suitable for HTML templating
                st = SearchTemplate(json_ld)
                st.process_json_ld()
                template = loader.get_template('search/view.html')
                context = RequestContext(request,
                                         {'st': st,
                                          'item_type': '*',
                                          'base_search_link': m_json_ld.base_search_link,
                                          'url': url,
                                          'json_url': json_url,
                                          'base_url': base_url})
                if req_neg.supported:
                    return HttpResponse(template.render(context))
                else:
                    # client wanted a mimetype we don't support
                    return HttpResponse(req_neg.error_message,
                                        content_type=req_neg.use_response_type + "; charset=utf8",
                                        status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)


# @cache_control(no_cache=True)
def json_view(request, spatial_context=None):
    """ API for searching Open Context """
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        cache_control(no_cache=True)
        return redirect('/search/.json', permanent=False)
    else:
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('search',
                                            request_dict_json)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.do_bot_limit = rd.do_bot_limit  # Toggle limits on facets for bots
            solr_s.mem_cache_obj = mem_cache_obj
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                mem_cache_obj = solr_s.mem_cache_obj  # reused cached memory items
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/search/'
                # share entities already looked up. Saves database queries
                m_json_ld.mem_cache_obj = mem_cache_obj
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('application/json')
            req_neg.supported_types = ['application/ld+json',
                                       'application/vnd.geo+json']
            recon_obj = Reconciliation()
            json_ld = recon_obj.process(request.GET,
                                        json_ld)
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if req_neg.supported:
                # requester wanted a mimetype we DO support
                if 'callback' in request.GET:
                    funct = request.GET['callback']
                    json_str = json.dumps(json_ld,
                                          ensure_ascii=False,
                                          indent=4)
                    return HttpResponse(funct + '(' + json_str + ');',
                                        content_type='application/javascript' + "; charset=utf8")
                else:
                    return HttpResponse(json.dumps(json_ld,
                                        ensure_ascii=False, indent=4),
                                        content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # client wanted a mimetype we don't support
                return HttpResponse(req_neg.error_message,
                                    status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)


# @cache_control(no_cache=True)
def subjects_html_view(request, spatial_context=None):
    """ returns HTML representation of subjects search
    """
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    csv_downloader = False  # provide CSV downloader interface
    if request.GET.get('csv') is not None:
        csv_downloader = True
    chart = False # provide a chart, now only experimental
    if request.GET.get('chart') is not None:
        chart = True
    rp = RootPath()
    base_url = rp.get_baseurl()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        cache_control(no_cache=True)
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        return redirect('/subjects-search/', permanent=False)
    else:
        # url and json_url neeed for view templating
        url = request.get_full_path()
        if 'http://' not in url \
           and 'https://' not in url:
            url = base_url + url
        if '?' in url:
            json_url = url.replace('?', '.json?')
        else:
            json_url = url + '.json'
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('subjects-search',
                                            request_dict_json)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.do_bot_limit = rd.do_bot_limit  # Toggle limits on facets for bots
            solr_s.mem_cache_obj = mem_cache_obj
            solr_s.item_type_limit = 'subjects'
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                mem_cache_obj = solr_s.mem_cache_obj  # reused cached memory items
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/subjects-search/'
                # share entities already looked up. Saves database queries
                m_json_ld.mem_cache_obj = mem_cache_obj
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                mem_cache_obj = m_json_ld.mem_cache_obj
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('text/html')
            req_neg.supported_types = ['application/json',
                                       'application/ld+json',
                                       'application/vnd.geo+json']
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if 'json' in req_neg.use_response_type:
                # content negotiation requested JSON or JSON-LD
                recon_obj = Reconciliation()
                json_ld = recon_obj.process(request.GET,
                                            json_ld)
                return HttpResponse(json.dumps(json_ld,
                                    ensure_ascii=False, indent=4),
                                    content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # now make the JSON-LD into an object suitable for HTML templating
                st = SearchTemplate(json_ld)
                st.process_json_ld()
                template = loader.get_template('search/view.html')
                props = []
                if 'prop' in request.GET:
                    props = request.GET.getlist('prop')
                if len(props) > 1 or st.total_count <= 25000:
                    # allow downloads, multiple props selected
                    # or relatively few records
                    csv_downloader = True
                context = RequestContext(request,
                                         {'st': st,
                                          'csv_downloader': csv_downloader,
                                          'chart': chart,
                                          'item_type': 'subjects',
                                          'base_search_link': m_json_ld.base_search_link,
                                          'url': url,
                                          'json_url': json_url,
                                          'base_url': base_url})
                if req_neg.supported:
                    return HttpResponse(template.render(context))
                else:
                    # client wanted a mimetype we don't support
                    return HttpResponse(req_neg.error_message,
                                        content_type=req_neg.use_response_type + "; charset=utf8",
                                        status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)


# @cache_control(no_cache=True)
def subjects_json_view(request, spatial_context=None):
    """ API for searching Open Context, subjects only """
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        cache_control(no_cache=True)
        return redirect('/subjects-search/.json', permanent=False)
    else:
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('subjects-search',
                                            request_dict_json)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.do_bot_limit = rd.do_bot_limit  # Toggle limits on facets for bots
            solr_s.mem_cache_obj = mem_cache_obj
            solr_s.item_type_limit = 'subjects'
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                mem_cache_obj = solr_s.mem_cache_obj  # reused cached memory items
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/subjects-search/'
                # share entities already looked up. Saves database queries
                m_json_ld.mem_cache_obj = mem_cache_obj
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                mem_cache_obj = m_json_ld.mem_cache_obj
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('application/json')
            req_neg.supported_types = ['application/ld+json',
                                       'application/vnd.geo+json']
            recon_obj = Reconciliation()
            recon_obj.mem_cache_obj = mem_cache_obj
            json_ld = recon_obj.process(request.GET,
                                        json_ld)
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if req_neg.supported:
                # requester wanted a mimetype we DO support
                if 'callback' in request.GET:
                    funct = request.GET['callback']
                    json_str = json.dumps(json_ld,
                                          ensure_ascii=False,
                                          indent=4)
                    return HttpResponse(funct + '(' + json_str + ');',
                                        content_type='application/javascript' + "; charset=utf8")
                else:
                    return HttpResponse(json.dumps(json_ld,
                                        ensure_ascii=False, indent=4),
                                        content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # client wanted a mimetype we don't support
                return HttpResponse(req_neg.error_message,
                                    status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)


# @cache_control(no_cache=True)
# @never_cache
def media_html_view(request, spatial_context=None):
    """ returns HTML representation of media search
    """
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    rp = RootPath()
    base_url = rp.get_baseurl()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        cache_control(no_cache=True)
        return redirect('/media-search/', permanent=False)
    else:
        # url and json_url neeed for view templating
        url = request.get_full_path()
        if 'http://' not in url \
           and 'https://' not in url:
            url = base_url + url
        if '?' in url:
            json_url = url.replace('?', '.json?')
        else:
            json_url = url + '.json'
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('media-search',
                                            request_dict_json)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.mem_cache_obj = mem_cache_obj
            solr_s.item_type_limit = 'media'
            # add category facet fields for related items
            solr_s.facet_fields += SolrSearch.REL_CAT_FACET_FIELDS
            solr_s.stats_fields += SolrSearch.MEDIA_STATS_FIELDS
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                mem_cache_obj = solr_s.mem_cache_obj  # reused cached memory items
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/media-search/'
                # share entities already looked up. Saves database queries
                m_json_ld.mem_cache_obj = mem_cache_obj
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                m_json_ld.get_all_media = True  # get links to all media files for an item
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('text/html')
            req_neg.supported_types = ['application/json',
                                       'application/ld+json',
                                       'application/vnd.geo+json']
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if 'json' in req_neg.use_response_type:
                # content negotiation requested JSON or JSON-LD
                recon_obj = Reconciliation()
                json_ld = recon_obj.process(request.GET,
                                            json_ld)
                return HttpResponse(json.dumps(json_ld,
                                    ensure_ascii=False, indent=4),
                                    content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # now make the JSON-LD into an object suitable for HTML templating
                st = SearchTemplate(json_ld)
                st.process_json_ld()
                template = loader.get_template('search/view.html')
                context = RequestContext(request,
                                         {'st': st,
                                          'item_type': 'media',
                                          'base_search_link': m_json_ld.base_search_link,
                                          'url': url,
                                          'json_url': json_url,
                                          'base_url': base_url})
                if req_neg.supported:
                    return HttpResponse(template.render(context))
                else:
                    # client wanted a mimetype we don't support
                    return HttpResponse(req_neg.error_message,
                                        content_type=req_neg.use_response_type + "; charset=utf8",
                                        status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)


# @cache_control(no_cache=True)
def media_json_view(request, spatial_context=None):
    """ API for searching Open Context, media only """
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        return redirect('/media-search/.json', permanent=False)
    else:
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('media-search',
                                            request_dict_json)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.do_bot_limit = rd.do_bot_limit  # Toggle limits on facets for bots
            solr_s.mem_cache_obj = mem_cache_obj
            solr_s.item_type_limit = 'media'
            # add category facet fields for related items
            solr_s.facet_fields += SolrSearch.REL_CAT_FACET_FIELDS
            solr_s.stats_fields += SolrSearch.MEDIA_STATS_FIELDS
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                mem_cache_obj = solr_s.mem_cache_obj  # reused cached memory items
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/media-search/'
                # share entities already looked up. Saves database queries
                m_json_ld.mem_cache_obj = mem_cache_obj
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                m_json_ld.get_all_media = True  # get links to all media files for an item
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('application/json')
            req_neg.supported_types = ['application/ld+json',
                                       'application/vnd.geo+json']
            recon_obj = Reconciliation()
            json_ld = recon_obj.process(request.GET,
                                        json_ld)
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if req_neg.supported:
                # requester wanted a mimetype we DO support
                if 'callback' in request.GET:
                    funct = request.GET['callback']
                    json_str = json.dumps(json_ld,
                                          ensure_ascii=False,
                                          indent=4)
                    return HttpResponse(funct + '(' + json_str + ');',
                                        content_type='application/javascript' + "; charset=utf8")
                else:
                    return HttpResponse(json.dumps(json_ld,
                                        ensure_ascii=False, indent=4),
                                        content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # client wanted a mimetype we don't support
                return HttpResponse(req_neg.error_message,
                                    status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)


# @cache_control(no_cache=True)
def projects_html_view(request, spatial_context=None):
    """ returns HTML representation of projects search
    """
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    rp = RootPath()
    base_url = rp.get_baseurl()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        cache_control(no_cache=True)
        return redirect('/projects-search/', permanent=False)
    else:
        # url and json_url neeed for view templating
        url = request.get_full_path()
        if 'http://' not in url \
           and 'https://' not in url:
            url = base_url + url
        if '?' in url:
            json_url = url.replace('?', '.json?')
        else:
            json_url = url + '.json'
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('projects-search',
                                            request_dict_json)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.do_bot_limit = rd.do_bot_limit  # Toggle limits on facets for bots
            solr_s.mem_cache_obj = mem_cache_obj
            solr_s.do_context_paths = False
            solr_s.item_type_limit = 'projects'
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                mem_cache_obj = solr_s.mem_cache_obj  # reused cached memory items
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/projects-search/'
                # share entities already looked up. Saves database queries
                m_json_ld.mem_cache_obj = mem_cache_obj
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('text/html')
            req_neg.supported_types = ['application/json',
                                       'application/ld+json',
                                       'application/vnd.geo+json']
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if 'json' in req_neg.use_response_type:
                # content negotiation requested JSON or JSON-LD
                recon_obj = Reconciliation()
                json_ld = recon_obj.process(request.GET,
                                            json_ld)
                return HttpResponse(json.dumps(json_ld,
                                    ensure_ascii=False, indent=4),
                                    content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # now make the JSON-LD into an object suitable for HTML templating
                st = SearchTemplate(json_ld)
                st.process_json_ld()
                p_aug = ProjectAugment(json_ld)
                p_aug.process_json_ld()
                template = loader.get_template('search/view.html')
                context = RequestContext(request,
                                         {'st': st,
                                          'item_type': 'projects',
                                          'base_search_link': m_json_ld.base_search_link,
                                          'p_aug': p_aug,
                                          'url': url,
                                          'json_url': json_url,
                                          'base_url': base_url})
                if req_neg.supported:
                    return HttpResponse(template.render(context))
                else:
                    # client wanted a mimetype we don't support
                    return HttpResponse(req_neg.error_message,
                                        content_type=req_neg.use_response_type + "; charset=utf8",
                                        status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)


# @cache_control(no_cache=True)
def projects_json_view(request, spatial_context=None):
    """ API for searching Open Context, media only """
    mem_cache_obj = MemoryCache()
    mem_cache_obj.ping_redis_server()
    rd = RequestDict()
    request_dict_json = rd.make_request_dict_json(request,
                                                  spatial_context)
    if rd.security_ok is False:
        template = loader.get_template('400.html')
        context = RequestContext(request,
                                 {'abusive': True})
        return HttpResponse(template.render(context), status=400)
    elif rd.do_bot_limit:
        # redirect bot requests away from faceted search where
        # they can negatively impact performance
        cache_control(no_cache=True)
        return redirect('/projects-search/', permanent=False)
    else:
        # see if search results are cached. this is not done
        # with a view decorator, because we want to handle bots differently
        db_cache = DatabaseCache()
        cache_key = db_cache.make_cache_key('projects-search',
                                            request_dict_json)
        if rd.refresh_cache:
            # the request wanted to refresh the cache
            db_cache.remove_cache_object(cache_key)
        # get the search result JSON-LD, if it exists in cache
        json_ld = db_cache.get_cache_object(cache_key)
        if json_ld is None:
            # cached result is not found, so make it with a new search
            solr_s = SolrSearch()
            solr_s.is_bot = rd.is_bot  # True if bot detected
            solr_s.do_bot_limit = rd.do_bot_limit  # Toggle limits on facets for bots
            solr_s.do_context_paths = False
            solr_s.item_type_limit = 'projects'
            if solr_s.solr is not False:
                response = solr_s.search_solr(request_dict_json)
                m_json_ld = MakeJsonLd(request_dict_json)
                m_json_ld.base_search_link = '/projects-search/'
                # share entities already looked up. Saves database queries
                m_json_ld.entities = solr_s.entities
                m_json_ld.request_full_path = request.get_full_path()
                m_json_ld.spatial_context = spatial_context
                json_ld = m_json_ld.convert_solr_json(response.raw_content)
                # now cache the resulting JSON-LD
                db_cache.save_cache_object(cache_key, json_ld)
        if json_ld is not None:
            req_neg = RequestNegotiation('application/json')
            req_neg.supported_types = ['application/ld+json',
                                       'application/vnd.geo+json']
            if 'HTTP_ACCEPT' in request.META:
                req_neg.check_request_support(request.META['HTTP_ACCEPT'])
            if req_neg.supported:
                # requester wanted a mimetype we DO support
                if 'callback' in request.GET:
                    funct = request.GET['callback']
                    json_str = json.dumps(json_ld,
                                          ensure_ascii=False,
                                          indent=4)
                    return HttpResponse(funct + '(' + json_str + ');',
                                        content_type='application/javascript' + "; charset=utf8")
                else:
                    return HttpResponse(json.dumps(json_ld,
                                        ensure_ascii=False, indent=4),
                                        content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                # client wanted a mimetype we don't support
                return HttpResponse(req_neg.error_message,
                                    status=415)
        else:
            cache_control(no_cache=True)
            template = loader.get_template('500.html')
            context = RequestContext(request,
                                     {'error': 'Solr Connection Problem'})
            return HttpResponse(template.render(context), status=503)
