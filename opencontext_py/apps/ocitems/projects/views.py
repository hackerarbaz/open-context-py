import json
from django.http import HttpResponse, Http404
from django.shortcuts import redirect
from opencontext_py.libs.rootpath import RootPath
from opencontext_py.libs.requestnegotiation import RequestNegotiation
from opencontext_py.apps.ocitems.ocitem.models import OCitem
from opencontext_py.apps.ocitems.ocitem.templating import TemplateItem
from opencontext_py.apps.ocitems.projects.content import ProjectContent
from django.template import RequestContext, loader
from opencontext_py.libs.general import LastUpdatedOrderedDict
from opencontext_py.apps.searcher.solrsearcher.models import SolrSearch
from opencontext_py.apps.searcher.solrsearcher.makejsonld import MakeJsonLd
from opencontext_py.apps.searcher.solrsearcher.filterlinks import FilterLinks
from opencontext_py.apps.searcher.solrsearcher.templating import SearchTemplate
from opencontext_py.apps.searcher.solrsearcher.requestdict import RequestDict
from opencontext_py.apps.searcher.solrsearcher.projtemplating import ProjectAugment
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import cache_control
from django.views.decorators.cache import never_cache


# Returns a search interface to browse projects
def index(request):
    """ redirects requests from the projects index
        to the project-search view
    """
    rp = RootPath()
    base_url = rp.get_baseurl()
    new_url =  base_url + '/projects-search/'
    return redirect(new_url, permanent=True)


# @cache_control(no_cache=True)
# @never_cache
def html_view(request, uuid):
    ocitem = OCitem()
    ocitem.get_item(uuid, True)
    if(ocitem.manifest is not False):
        rp = RootPath()
        base_url = rp.get_baseurl()
        proj_content = ProjectContent(ocitem.manifest.uuid,
                                      ocitem.manifest.slug,
                                      ocitem.json_ld)
        temp_item = TemplateItem()
        temp_item.proj_content = proj_content.get_project_content()
        temp_item.read_jsonld_dict(ocitem.json_ld)
        template = loader.get_template('projects/view.html')
        req_neg = RequestNegotiation('text/html')
        req_neg.supported_types = ['application/json',
                                   'application/ld+json',
                                   'application/vnd.geo+json']
        if 'HTTP_ACCEPT' in request.META:
            req_neg.check_request_support(request.META['HTTP_ACCEPT'])
        if req_neg.supported:
            if 'json' in req_neg.use_response_type:
                # content negotiation requested JSON or JSON-LD
                return HttpResponse(json.dumps(ocitem.json_ld,
                                    ensure_ascii=False, indent=4),
                                    content_type=req_neg.use_response_type + "; charset=utf8")
            else:
                context = RequestContext(request,
                                         {'item': temp_item,
                                          'base_url': base_url})
                return HttpResponse(template.render(context))
        else:
                # client wanted a mimetype we don't support
                return HttpResponse(req_neg.error_message,
                                    content_type=req_neg.use_response_type + "; charset=utf8",
                                    status=415)
    else:
        raise Http404


def json_view(request, uuid):
    ocitem = OCitem()
    if 'hashes' in request.GET:
        ocitem.assertion_hashes = True
    ocitem.get_item(uuid, True)
    if(ocitem.manifest is not False):
        req_neg = RequestNegotiation('application/json')
        req_neg.supported_types = ['application/ld+json',
                                   'application/vnd.geo+json']
        if 'HTTP_ACCEPT' in request.META:
            req_neg.check_request_support(request.META['HTTP_ACCEPT'])
        if req_neg.supported:
            json_output = json.dumps(ocitem.json_ld,
                                     indent=4,
                                     ensure_ascii=False)
            if 'callback' in request.GET:
                funct = request.GET['callback']
                return HttpResponse(funct + '(' + json_output + ');',
                                    content_type='application/javascript' + "; charset=utf8")
            else:
                return HttpResponse(json_output,
                                    content_type=req_neg.use_response_type + "; charset=utf8")
        else:
            # client wanted a mimetype we don't support
            return HttpResponse(req_neg.error_message,
                                content_type=req_neg.use_response_type + "; charset=utf8",
                                status=415)
    else:
        raise Http404
