import json
from django.http import HttpResponse, Http404
from django.shortcuts import redirect
from opencontext_py.libs.rootpath import RootPath
from opencontext_py.libs.requestnegotiation import RequestNegotiation
from opencontext_py.apps.ocitems.ocitem.models import OCitem
from opencontext_py.apps.ocitems.ocitem.templating import TemplateItem
from django.template import RequestContext, loader


# A media resource describes metadata about a binary file (usually an image)
# A media resource will have links to different versions of the binary file
# so that thumbnail, preview, and other versions can be discovered. However
# these other versions are "part" of an abstract media resource
def index(request):
    """ redirects requests from the media index
        to the media-search view
    """
    rp = RootPath()
    base_url = rp.get_baseurl()
    new_url =  base_url + '/media-search/'
    return redirect(new_url, permanent=True)


def html_view(request, uuid):
    ocitem = OCitem()
    ocitem.get_item(uuid)
    if(ocitem.manifest is not False):
        rp = RootPath()
        base_url = rp.get_baseurl()
        temp_item = TemplateItem(request)
        temp_item.read_jsonld_dict(ocitem.json_ld)
        template = loader.get_template('media/view.html')
        if temp_item.view_permitted:
            req_neg = RequestNegotiation('text/html')
            req_neg.supported_types = ['application/json',
                                       'application/ld+json']
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
                                              'fullview': False,
                                              'base_url': base_url})
                    return HttpResponse(template.render(context))
            else:
                # client wanted a mimetype we don't support
                return HttpResponse(req_neg.error_message,
                                    content_type=req_neg.use_response_type + "; charset=utf8",
                                    status=415)
        else:
            template = loader.get_template('items/view401.html')
            context = RequestContext(request,
                                     {'item': temp_item,
                                      'base_url': base_url})
            return HttpResponse(template.render(context), status=401)
    else:
        raise Http404


def html_full(request, uuid):
    ocitem = OCitem()
    if 'hashes' in request.GET:
        ocitem.assertion_hashes = True
    ocitem.get_item(uuid)
    if(ocitem.manifest is not False):
        rp = RootPath()
        base_url = rp.get_baseurl()
        temp_item = TemplateItem(request)
        temp_item.read_jsonld_dict(ocitem.json_ld)
        template = loader.get_template('media/full.html')
        if temp_item.view_permitted:
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
                                              'fullview': True,
                                              'base_url': base_url})
                    return HttpResponse(template.render(context))
            else:
                # client wanted a mimetype we don't support
                return HttpResponse(req_neg.error_message,
                                    content_type=req_neg.use_response_type + "; charset=utf8",
                                    status=415)
        else:
            template = loader.get_template('items/view401.html')
            context = RequestContext(request,
                                     {'item': temp_item,
                                      'base_url': base_url})
            return HttpResponse(template.render(context), status=401)
    else:
        raise Http404


def json_view(request, uuid):
    ocitem = OCitem()
    if 'hashes' in request.GET:
        ocitem.assertion_hashes = True
    ocitem.get_item(uuid)
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
