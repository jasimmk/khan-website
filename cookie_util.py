import Cookie
import logging
import os
from app import App


def get_cookie_value(key):
    cookies = None
    try:
        cookies = Cookie.BaseCookie(os.environ.get('HTTP_COOKIE', ''))
    except Cookie.CookieError, error:
        logging.debug("Ignoring Cookie Error, skipping get cookie: '%s'"
                      % error)

    if not cookies:
        return None

    cookie = cookies.get(key)

    if not cookie:
        return None

    return cookie.value


def get_google_cookie():
    """ Retrieves the auth cookie value used to authenticate Google users with
    appengine over HTTP.

    This does no validation of the value.
    
    """

    if App.is_dev_server:
        return get_cookie_value('dev_appserver_login')
    else:
        return get_cookie_value('ACSID')


# Cookie handling from
# http://appengine-cookbook.appspot.com/recipe/a-simple-cookie-class/
def set_cookie_value(key, value='', max_age=None,
               path='/', domain=None, secure=None, httponly=False,
               version=None, comment=None):
    cookies = Cookie.BaseCookie()
    cookies[key] = value
    for var_name, var_value in [
        ('max-age', max_age),
        ('path', path),
        ('domain', domain),
        ('secure', secure),
        #('HttpOnly', httponly), Python 2.6 is required for httponly cookies
        ('version', version),
        ('comment', comment),
        ]:
        if var_value is not None and var_value is not False:
            cookies[key][var_name] = str(var_value)
    if max_age is not None:
        cookies[key]['expires'] = max_age

    cookies_header = cookies[key].output(header='').lstrip()

    if httponly:
        # We have to manually add this part of the header until GAE
        # uses Python 2.6.
        cookies_header += "; HttpOnly"

    return cookies_header


def set_request_cookie(key, value):
    ''' Set a cookie for the remainder of the request
    This does NOT set a cookie on the user's computer. This only makes it
    appear that it's set on their computer while their request is being
    completed. For instance this is currently used when a phantom user is
    created to make it appear that the user already has the phantom user cookie
    set on their computer.
    '''
    try:
        allcookies = Cookie.BaseCookie(os.environ.get('HTTP_COOKIE', ''))
    except Cookie.CookieError, error:
        logging.critical("Ignoring Cookie Error: '%s'" % error)

    # now set a fake cookie for this request
    allcookies[key] = value
    os.environ['HTTP_COOKIE'] = allcookies.output()
