"""Interface to Sailthru API."""

import hashlib
import itertools
import socket
import urllib
import urllib2

try:
    # Prefer simplejson as it's usually faster
    import simplejson as json
except ImportError:
    import json

try:
    import settings
except ImportError:
    class settings:
        class services:
            sailthru = {
                'server': 'api.sailthru.com',
                'key': 'YOUR-KEY-HERE',
                'secret': 'YOUR-SECRET-HERE',
            }

TIMEOUT = 10

class Error(Exception):
    """A Sailthru error."""

    def __init__(self, error_code=0, error_msg='None'):
        self.args = (error_code, error_msg)
        self.error_code = error_code
        self.error_msg = error_msg

class UrlMethodRequest(urllib2.Request):
    """Subclass Request so we can override get_method() to allow non-GET/POST methods."""

    def __init__(self, method, *args, **kwargs):
        self._method = method
        urllib2.Request.__init__(self, *args, **kwargs)

    def get_method(self):
        return self._method

def safestr(obj):
    r"""Convert given object to utf-8 encoded string (from web.py).
    
    >>> safestr('hello')
    'hello'
    >>> safestr(u'\u1234')
    '\xe1\x88\xb4'
    >>> safestr(2)
    '2'

    """
    if isinstance(obj, unicode):
        return obj.encode('utf-8')
    elif isinstance(obj, str):
        return obj
    elif hasattr(obj, 'next') and hasattr(obj, '__iter__'): # iterator
        return itertools.imap(safestr, obj)
    else:
        return str(obj)

def _flatten(dictionary, base_key='', output=None):
    r"""Return flattened version of given dictionary. Values in nested dictionaries are
    placed in the output with keys "k0[k1]", where k0 is the key of the dict in the top
    dict and k1 is the key of the value in the inner dict.
    
    >>> _flatten({})
    {}
    >>> sorted(_flatten({'k': 'v'}).items())
    [('k', 'v')]
    >>> sorted(_flatten({'k1': 'v1', 'k2': {'k3': {'k4': 'v2'}, 'k5': 'v3'}}).items())
    [('k1', 'v1'), (u'k2[k3][k4]', 'v2'), (u'k2[k5]', 'v3')]
    >>> sorted(_flatten({'k%c': 'v%c'}).items())
    [('k%c', 'v%c')]
    >>> sorted(_flatten({'k1%c': {'k2%c': 'v1%c'}}).items())
    [(u'k1%c[k2%c]', 'v1%c')]
    >>> sorted(_flatten({'k1': {u'o\u2019kane': u'o\u2019hare'}}).items())
    [(u'k1[o\u2019kane]', u'o\u2019hare')]

    """
    if output is None:
        output = {}
    for key, value in dictionary.iteritems():
        if base_key:
            inner_key = u'{0}[{1}]'.format(base_key, key)
        else:
            inner_key = key
        if hasattr(value, 'iteritems'):
            _flatten(value, inner_key, output)
        else:
            output[inner_key] = value
    return output

def _sailthru_request(action, method, kw):
    """ 
    @raise: sailthru.Error
    """
    assert method in ('GET', 'POST', 'DELETE')

    kw['api_key'] = settings.services.sailthru['key']
    kw['format'] = 'json'
    if action == 'send' and 'vars' in kw:
        kw['vars'] = json.dumps(kw['vars'])
    kw = _flatten(kw)

    # Ensure keys and values are encoded as UTF-8
    kw = dict((safestr(k), safestr(v)) for k, v in kw.iteritems())
    values = sorted(kw.itervalues())
    kw['sig'] = hashlib.md5(settings.services.sailthru['secret'] + ''.join(values)).hexdigest()
    query = urllib.urlencode(kw)
    url = 'http://' + settings.services.sailthru['server'] + '/' + action
    data = None
    headers = {}
    if method == 'POST':
        data = query
    else:
        url += '?' + query

    http_error = None
    try:
        request = UrlMethodRequest(method, url, data=data, headers=headers)
        response = urllib2.urlopen(request, timeout=TIMEOUT)
        response = response.read()
    except urllib2.HTTPError as e:
        response = e.read()
        http_error = e
    except (urllib2.URLError, socket.error) as e:
        raise Error(-1, 'No Connection: ' + str(e))

    try:
        json_response = json.loads(response)
    except (TypeError, ValueError) as e:
        error_message = "{0}Malformed JSON, couldn't parse: {1} - {2!r}".format(
                str(http_error) + ' - ' if http_error else '',
                e, response[:100])
        raise Error(-2, error_message)

    if 'error' in json_response:
        raise Error(json_response['error'], json_response['errormsg'])

    return json_response

def send_mail(template, to_address, bcc=None, **kw):
    """ Send an email. If a single email address is given (and optionally a bcc address),
        return the Sailthru send_id of the email. If multiple, comma-separated email
        addresses are given, return a dictionary of {email: send_id} pairs.

    @param vars: dict of replacement variables for this particular email
            Special variables:
            name - Name to put on the "To" line like "Joe Example" <joe@example.com>
            from_email - Sets the from email address, it must already be an approved sender address
    @param options: dict with
            replyto - override the Reply-To header
            test - Set to 1 for a test email.  'TEST:' will be put on subject line, 
                   and it will not count towards stats 
    @raise: sailthru.Error
    """

    kw['template'] = template
    kw['email'] = to_address
    if bcc:
        # Not a real bcc, but with Sailthru this acts as a bcc
        kw['email'] += ',' + bcc

    response = _sailthru_request('send', 'POST', kw)

    if 'send_ids' in response:
        if bcc:
            if to_address in response['send_ids']:
                return response['send_ids'][to_address]
            else:
                # Didn't go through. Because we're bcc'ing, we don't get error
                # information, so use our best guess
                raise Error(34, 'Email may not be emailed')
        else:
            return response['send_ids']
    elif 'send_id' in response:
        return response['send_id']
    else:
        raise Error(-2, 'Malformed JSON: no send_id(s)')

def cancel_mail(send_id):
    """Cancel email with given send_id that was previously scheduled to be sent.
    
    @raise: sailthru.Error
    """
    return _sailthru_request('send', 'DELETE', {'send_id': send_id})

def update_blast(blast_id, **kw):
    """Update Sailthru blast with given keyword parameters. See also:
    http://docs.sailthru.com/api/blast
    
    """
    kw['blast_id'] = blast_id
    return _sailthru_request('blast', 'POST', kw)

def send_blast(name, list_name, from_name, from_email, subject, html, text='',
               schedule_time='now', reply_to=None, link_tracking=True,
               google_analytics=True, public=True, ehash=True, utm_content=True, **kw):
    """Send or schedule a mass mail blast and return the blast ID. For full list of
    optional kw parameters, see http://docs.sailthru.com/api/blast
    
    @raise: sailthru.Error - if Sailthru error occurs or error talking to Sailthru

    """
    kw['name'] = name
    kw['list'] = list_name
    kw['from_name'] = from_name
    kw['from_email'] = from_email
    kw['subject'] = subject
    kw['content_html'] = html
    kw['content_text'] = text
    if schedule_time is not None:
        kw['schedule_time'] = schedule_time
    if reply_to is not None:
        kw['replyto'] = reply_to
    if link_tracking is not None:
        kw['is_link_tracking'] = '1' if link_tracking else '0'
    if google_analytics is not None:
        kw['is_google_analytics'] = '1' if google_analytics else '0'
    if public is not None:
        kw['is_public'] = '1' if public else '0'
    link_params = {}
    if ehash:
        link_params['_ehash'] = "{md5(email)}"
    if utm_content:
        link_params['utm_content'] = "{source}"
    kw['link_params'] = json.dumps(link_params)

    response = _sailthru_request('blast', 'POST', kw)

    if 'blast_id' not in response:
        raise Error(-2, 'Malformed JSON: blast_id not in response')
    return response['blast_id']

def get_user_blasts(email_address, num_blasts):
    """Get the last x blasts sent to a user

    @raise: sailthru.Error
    """
    blasts = []

    user = get_user_properties(email_address, recent_blasts=num_blasts)
    if user['recent_blasts']:
        for blast in user['recent_blasts']:
            blast.update(get_blast_properties(blast['blast_id']))
            blasts.append(blast)

    return blasts

def get_blast_properties(blast_id):
    """ Gets information about a campaign mail

    @raise: sailthru.Error
    """

    return _sailthru_request('blast', 'GET', {'blast_id': blast_id})

def get_email_properties(send_id):
    """ Gets information about a sent email

    @raise: sailthru.Error
    """
    return _sailthru_request('send', 'GET', {'send_id': send_id})

def get_user_properties(email_address, **kw):
    """ Get information about an email address

    @param recent_sends:  Get last x transactional mails sent to user
    @param recent_blasts:  Get last x blast mails sent to user

    @raise: sailthru.Error
    """

    properties = { 'verified': 0, # Has a user confirmed their email address
                   'optout': 0 } # Has a user opted-out of Oyster emails

    vars = {'email': email_address}
    vars.update(kw)
    response = _sailthru_request('email', 'GET', vars)

    properties.update(response)
    return properties

def set_user_properties(email, **kw):
    """ Set properties on a user 

    @raise: sailthru.Error
    """

    kw['email'] = email
    return _sailthru_request('email', 'POST', kw)

def get_template_properties(template):
    """ Get information about a template
     As far as i can tell, 'html' is the only useful field of the result 

    @raise: sailthru.Error
    """

    return _sailthru_request('template', 'GET', {'template': template})

def set_template_properties(template, **kw):
    """ Set template properties 

    @raise: sailthru.Error
    """

    kw['template'] = template
    return _sailthru_request('template', 'POST', kw)

def set_user_lists(email, lists, add=True):
    """ Add or remove a user from some lists

    @param email: Email address of user
    @param lists: A string or a list of strings that are the list names

    @raise: sailthru.Error
    """

    if isinstance(lists, basestring):
        lists = [lists]

    if add:
        list_value = 1
    else:
        list_value = 0

    kw = {}
    kw['email'] = email
    kw['lists'] = {}
    for list in lists:
        kw['lists'][list] = list_value

    return _sailthru_request('email', 'POST', kw)

def add_users_to_list(list_name, emails, report_email=None):
    """Add list of emails to given list.  Optionally send an email to report_email when finished.

    @raise: sailthru.Error
    """

    params = {}
    if report_email:
        params['report_email'] = report_email
    params['job'] = 'import'
    params['list'] = list_name
    params['emails'] = ','.join(emails)
    
    return _sailthru_request('job', 'POST', params)

def set_vars(url, report_email=None):
    """Set large number of per-user vars using given CSV data feed URL.

    @raise: sailthru.Error
    """
    kw = {'url': url}
    if report_email:
        kw['report_email'] = report_email
    return _sailthru_request('vars', 'POST', kw)

if __name__ == '__main__':
    import doctest
    doctest.testmod()
