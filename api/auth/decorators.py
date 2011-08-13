from functools import wraps

import flask
from flask import request

from api.auth.auth_util import oauth_error_response
from api.auth.auth_models import OAuthMap

from oauth_provider.decorators import is_valid_request, validate_token
from oauth_provider.oauth import OAuthError

import util

# Decorator for validating an oauth request and storing the OAuthMap for use
# in the rest of the request.
#
# If oauth credentials don't pass, return an error.
def oauth_required(require_anointed_consumer = False):
    def outer_wrapper(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if is_valid_request(request):
                try:
                    consumer, token, parameters = validate_token(request)
                    if consumer and token:

                        # If this API method requires an anointed consumer,
                        # restrict any that haven't been manually approved.
                        if require_anointed_consumer and not consumer.anointed:
                            return oauth_error_response(OAuthError("Consumer access denied."))

                        # Store the OAuthMap containing all auth info in the request global
                        # for easy access during the rest of this request.
                        flask.g.oauth_map = OAuthMap.get_from_access_token(token.key_)

                        if not util.get_current_user_id():
                            # If our OAuth provider thinks you're logged in but the 
                            # identity providers we consume (Google/Facebook) disagree,
                            # we act as if our token is no longer valid.
                            return oauth_error_response(OAuthError("Unable to get current user from oauth token."))

                        return func(*args, **kwargs)

                except OAuthError, e:
                    return oauth_error_response(e)

            return oauth_error_response(OAuthError("Invalid OAuth parameters"))
        return wrapper
    return outer_wrapper

# Decorator for validating an oauth request and storing the OAuthMap for use
# in the rest of the request.
#
# If oauth credentials don't pass, continue on, but util.get_current_user_id() will return None.
def oauth_optional():
    def outer_wrapper(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if is_valid_request(request):
                try:
                    consumer, token, parameters = validate_token(request)
                    if consumer and token:

                        # Store the OAuthMap containing all auth info in the request global
                        # for easy access during the rest of this request.
                        flask.g.oauth_map = OAuthMap.get_from_access_token(token.key_)

                        if not util.get_current_user_id():
                            # If our OAuth provider thinks you're logged in but the 
                            # identity providers we consume (Google/Facebook) disagree,
                            # we act as if our token is no longer valid.
                            flask.g.oauth_map = None

                except OAuthError, e:
                    # OAuthErrors are ignored, treated as user that's just not logged in
                    pass

            # Run decorated function regardless of whether or not oauth succeeded
            return func(*args, **kwargs)

        return wrapper
    return outer_wrapper
