import sys
from time import sleep
from opencontext_py.apps.ldata.tdar.api import tdarAPI
from opencontext_py.apps.edit.dinaa.trinomials.models import Trinomial
from opencontext_py.apps.edit.dinaa.trinomials.manage import TrinomialManage
from opencontext_py.apps.ocitems.manifest.models import Manifest
from opencontext_py.apps.ldata.linkentities.models import LinkEntity
from opencontext_py.apps.ldata.linkannotations.models import LinkAnnotation


class dinaaLink():
    """ methods to link Smithsonian Trinomials curated by
        DINAA with keywords in tDAR
    """
    DC_TERMS_SUBJECT = 'dc-terms:subject'
    TDAR_VOCAB = 'http://core.tdar.org/browse/site-name/'

    def __init__(self):
        self.request_error = False
        self.lead_zero_check = True
        self.max_results = 3
        self.error_wait = 0  # wait if problem to send next request
        self.base_wait = 300
        self.max_wait = self.base_wait * 5

    def match_dinaa_ids(self, limit=False):
        """ get a key word for a site """
        found_matches = 0
        if limit is not False:
            tris = Trinomial.objects.filter(trinomial__isnull=False,
                                            tdar_checked__isnull=True)[:limit]
        else:
            tris = Trinomial.objects.filter(trinomial__isnull=False,
                                            tdar_checked__isnull=True)
        len_tris = len(tris)
        i = 1
        for tri in tris:
            found_matches += self.match_trinomial_obj(tri)
            if self.request_error is False:
                tri.tdar_checked_save()
                print('Total tDAR matches: ' + str(found_matches) + ', Checked item: ' + str(i) + ' of ' + str(len_tris))
            i += 1
        return found_matches

    def match_trinomial_obj(self, tri):
        """ Attempts to match a trinomial object 'tri'
            against tDAR, if it hasn't yet been matched
        """
        found_matches = 0
        manifest = False
        try:
            manifest = Manifest.objects.get(uuid=tri.uuid)
        except Manifest.DoesNotExist:
            manifest = False
        la_check = LinkAnnotation.objects\
                                 .filter(subject=tri.uuid,
                                         predicate_uri='dc-terms:subject',
                                         object_uri__contains=self.TDAR_VOCAB)[:1]
        if len(la_check) < 1 and manifest is not False:
            # we don't already have a tDAR id for this item, continue with matches
            tri_man = TrinomialManage()
            request_keywords = [tri.trinomial]
            if self.lead_zero_check:
                # check multiple leading zeros
                tri_parts = tri_man.parse_trinomial(tri.trinomial)
                site = tri_parts['site']
                site_part_len = len(site)
                while len(site) < 4:
                    site = '0' + site
                    new_trinomial = tri_parts['state'] + tri_parts['county'] + site
                    request_keywords.append(new_trinomial)
            for keyword in request_keywords:
                tdar_api = tdarAPI()
                results = tdar_api.get_site_keyword(keyword)
                if isinstance(results, list):
                    for result in results[:self.max_results]:
                        # assume it is a spurious match
                        match_real = False
                        if result['label'] == tri.trinomial:
                            # the trinomial and the tDAR result exactly match
                            match_real = True
                        else:
                            # check if the only difference is in leading zeros
                            tri_parts = tri_man.parse_trinomial(tri.trinomial)
                            site = tri_parts['site']
                            site_part_len = len(site)
                            while len(site) < 5:
                                site = '0' + site
                                new_trinomial = tri_parts['state'] + tri_parts['county'] + site
                                if new_trinomial == result['label']:
                                    # A good match, the tDAR result and the trinomial
                                    # match (but with different leading zeros)
                                    match_real = True
                        if match_real:
                            found_matches += 1
                            # OK! Found a match, first save the linked entity in the link entity table
                            le_check = False
                            try:
                                le_check = LinkEntity.objects.get(uri=result['id'])
                            except LinkEntity.DoesNotExist:
                                le_check = False
                            if le_check is False:
                                le = LinkEntity()
                                le.uri = result['id']
                                le.label = result['label']
                                le.alt_label = result['label']
                                le.vocab_uri = self.TDAR_VOCAB
                                le.ent_type = 'type'
                                le.save()
                            # Now save the link annotation
                            la = LinkAnnotation()
                            la.subject = tri.uuid
                            la.subject_type = manifest.item_type
                            la.project_uuid = manifest.project_uuid
                            la.source_id = 'tdar-api-lookup'
                            la.predicate_uri = self.DC_TERMS_SUBJECT
                            la.object_uri = result['id']
                            la.save()
                        else:
                            print('Almost! ' + result['label'] + ' is not exactly: ' + tri.trinomial)
                if tdar_api.request_error:
                    self.request_error = True
                    print('HTTP request to tDAR failed!')
                    self.error_wait += self.base_wait
                    if self.error_wait > self.max_wait:
                        print('Too many failures, quiting...')
                        sys.exit('Quitting process')
                    else:
                        # sleep some minutes before trying again
                        print('Will try again in ' + str(self.error_wait) + ' seconds...')
                        sleep(self.error_wait)
                else:
                    self.request_error = False
                    if self.error_wait >= self.base_wait:
                        print('HTTP requests resumed OK, will continue.')
                        self.error_wait = 0
        return found_matches
