import itertools
import django.utils.http as http
from opencontext_py.apps.entities.entity.models import Entity
from opencontext_py.apps.ocitems.assertions.containment import Containment


class ViewUtilities():
    '''
    Various methods useful for parsing URIs, requests, and processing user
    input
    '''

    def _get_context_paths(spatial_context):
        '''
        Takes a context path and returns an iterator with the list of possible
        contexts. Parses the list of boolean '||' (OR) and returns a list
        of contexts.

        For example:

        >>> _get_context_paths('Turkey/Domuztepe/I||II||Stray')

        ['Turkey/Domuztepe/I', 'Turkey/Domuztepe/II', 'Turkey/Domuztepe/Stray']

        '''
        # Split the context path by '/' and then by '||'
        context_lists = (value.split('||') for value in
                         spatial_context.split('/'))
        # Create lists of the various permutations
        context_tuple_list = list(itertools.product(*context_lists))
        # Turn the lists back into URIs
        return ('/'.join(value) for value in context_tuple_list)

    def _get_context_depth(spatial_context):
        '''
        Takes a context path and returns its depth as an interger. For
        example, the context '/Turkey/Domuztepe'
        would have a depth of 2.
        '''
        # Remove a possible trailing slash before calculating the depth
        return len(spatial_context.rstrip('/').split('/'))

    def _get_valid_context_slugs(contexts):
        '''
        Takes a list of contexts and, for valid contexts, returns a list of
        slugs
        '''
        entity = Entity()
        valid_context_slugs = []
        context_list = list(contexts)
        for context in context_list:
            # Remove the '+' characters to match values in the database
            context = http.urlunquote_plus(context)
            # Verify that the contexts are valid
            found = entity.context_dereference(context)
            if found:
                # If so, we want their slugs
                valid_context_slugs.append(entity.slug)
        return valid_context_slugs

    def _get_parent_slug(slug):
        '''
        Takes a slug and returns the slug of its parent. It returns False if
        a slug has no parent.
        '''
        return Containment().get_parent_slug_by_slug(slug)

    # TODO process parents - perhaps break up _get_valid_context_slug
    # so that it just returns valid URIs. Then we could get the slugs with a
    # separate method that could also request slugs for the parent.