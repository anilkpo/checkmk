#!/usr/bin/python
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2012             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# ails.  You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.

import config

# FIXME: For some reason mod_python is missing /usr/lib/python2.7/dist-packages
# in sys.path. Therefor the ldap module can not be found. Need to fix this!
import sys ; sys.path.append('/usr/lib/python2.7/dist-packages')
try:
    # docs: http://www.python-ldap.org/doc/html/index.html
    import ldap
    import ldap.filter
except:
    pass
from lib import *

# LDAP attributes are case insensitive, we only use lower case!
ldap_attr_map = {
    'ad': {
        'user_id': 'samaccountname',
    },
    'openldap': {
        'user_id': 'uid',
    },
}

# LDAP attributes are case insensitive, we only use lower case!
user_filter = {
    'ad':       '(&(objectclass=user)(objectcategory=person))',
    'openldap': '(objectcategory=user)',
}

#
# GENERAL LDAP CODE
# FIXME: Maybe extract to central lib
#

class MKLDAPException(MKGeneralException):
    pass

ldap_connection = None

def ldap_uri():
    if config.ldap_connection.get('use_ssl', False):
        uri = 'ldaps://'
    else:
        uri = 'ldap://'

    return uri + '%s:%d' % (config.ldap_connection['server'], config.ldap_connection['port'])

def ldap_connect():
    global ldap_connection
    if ldap_connection:
        return # Only initialize once.

    try:
        ldap
    except:
        raise MKLDAPException(_("The python module python-ldap seem to be missing. You need to "
                                "install this extension to make the LDAP user connector work."))

    # Some major config var validations

    if not config.ldap_connection.get('server'):
        raise MKLDAPException(_('The LDAP connector is enabled in global settings, but the '
                                'LDAP server to connect to is not configured. Please fix this in the '
                                '<a href="wato.py?mode=edit_configvar&varname=ldap_connection">LDAP '
                                'connection settings</a>.'))

    if not config.ldap_userspec.get('user_dn'):
        raise MKLDAPException(_('The distinguished name of the container object, which holds '
                                'the user objects to be authenticated, is not configured. Please '
                                'fix this in the <a href="wato.py?mode=edit_configvar&varname=ldap_userspec">'
                                'LDAP User Settings</a>.'))

    try:
        ldap_connection = ldap.ldapobject.ReconnectLDAPObject(ldap_uri())
        ldap_connection.protocol_version = config.ldap_connection['version']
        ldap_default_bind()

    except ldap.LDAPError, e:
        raise MKLDAPException(e)

# Bind with the default credentials
def ldap_default_bind():
    if config.ldap_connection['bind']:
        ldap_bind(config.ldap_connection['bind'][0],
                  config.ldap_connection['bind'][1])
    else:
        ldap_bind('', '') # anonymous bind

def ldap_bind(username, password):
    try:
        ldap_connection.simple_bind_s(username, password)
    except ldap.LDAPError, e:
        raise MKLDAPException(_('Unable to authenticate with LDAP (%s)' % e))

def ldap_search(base, filt = '(objectclass=*)', columns = [], scope = None):
    if scope:
        config_scope = scope
    else:
        config_scope = config.ldap_userspec.get('scope', 'sub')

    if config_scope == 'sub':
        scope = ldap.SCOPE_SUBTREE
    elif config_scope == 'base':
        scope = ldap.SCOPE_BASE
    elif config_scope == 'one':
        scope = ldap.SCOPE_ONELEVEL

    # Convert all keys to lower case!
    result = []
    for dn, obj in ldap_connection.search_s(base, scope, filt, columns):
        new_obj = {}
        for key, val in obj.iteritems():
            new_obj[key.lower()] = val
        result.append((dn, new_obj))
    return result
    #return ldap_connection.search_s(base, scope, filter, columns)
    #for dn, obj in ldap_connection.search_s(base, scope, filter, columns):
    #    html.log(repr(dn) + ' ' + repr(obj))

# Returns the ldap attribute name depending on the configured ldap directory type
# If a key is not present in the map, the assumption is, that the key matches 1:1
def ldap_attr(key):
    return ldap_attr_map[config.ldap_connection['type']].get(key, key)

def ldap_attrs(keys):
    return map(ldap_attr, keys)

def get_user_dn(username):
    # Check wether or not the user exists in the directory
    # It's only ok when exactly one entry is found.
    # Returns the DN in this case.
    result = ldap_search(
        config.ldap_userspec['user_dn'],
        '(%s=%s)' % (ldap_attr('user_id'), ldap.filter.escape_filter_chars(username)),
        [key],
    )

    if result:
        return result[0][0]

def ldap_get_users(add_filter = None):
    columns = [
        ldap_attr('user_id'),
    ] + ldap_needed_attributes()

    filt = user_filter[config.ldap_connection['type']]
    if add_filter:
        filt = '(&%s%s)' % (filt, add_filter)

    result = {}
    for dn, ldap_user in ldap_search(config.ldap_userspec['user_dn'], filt, columns = columns):
        user_id = ldap_user[ldap_attr('user_id')][0]
        result[user_id] = ldap_user

    return result

#
# Attribute plugin handling
#

ldap_attribute_plugins = {}

# Returns a list of pairs (key, title) of all available attribute plugins
def ldap_list_attribute_plugins():
    plugins = []
    for key, plugin in ldap_attribute_plugins.items():
        plugins.append((key, plugin['title']))
    return plugins

# Returns a list of all needed LDAP attributes of all enabled plugins
def ldap_needed_attributes():
    attrs = set([])
    for key in config.ldap_active_plugins:
        attrs.update(ldap_attribute_plugins[key]['needed_attributes']())
    return list(attrs)

def ldap_convert_simple(user_id, ldap_user, wato_attr, attr):
    return {wato_attr: ldap_user[ldap_attr(attr)][0]}

def ldap_convert_mail(user_id, ldap_user):
    mail = ''
    if ldap_user.get(ldap_attr('mail')):
        mail = ldap_user[ldap_attr('mail')][0].lower()
    return {'email': mail}

ldap_attribute_plugins['email'] = {
    'title': _('Email address'),
    'help':  _('Synchronizes the email of the LDAP user account into Check_MK.'),
    # Attributes which must be fetched from ldap
    'needed_attributes': lambda: ldap_attrs(['mail']),
    # Optional: ValueSpec for configuring this plugin
    # 'config': 
    # Calculating the value of the attribute based on the configuration and the values
    # gathered from ldap
    'convert': ldap_convert_mail,
    # User-Attributes to be written by this plugin and will be locked in WATO
    'set_attributes': [ 'email' ],
}

ldap_attribute_plugins['alias'] = {
    'title': _('Alias'),
    'help':  _('Synchronizes the alias of the LDAP user account into Check_MK.'),
    'needed_attributes': lambda: ldap_attrs(['cn']),
    'convert':           lambda user_id, ldap_user: ldap_convert_simple(user_id, ldap_user, 'alias', 'cn'),
    'set_attributes':    [ 'alias' ],
}

#
# Connector hook functions
#

def ldap_login(username, password):
    ldap_connect()
    # Returns None when the user is not found or not uniq, else returns the
    # distinguished name of the user as string which is needed for the login.
    user_dn = get_user_dn(username)
    if not user_dn:
        return None # The user does not exist. Skip this connector.

    # Try to bind with the user provided credentials. This unbinds the default
    # authentication which should be rebound again after trying this.
    try:
        ldap_bind(user_dn, password)
        result = True
    except:
        result = False

    ldap_default_bind()
    return result

def ldap_sync(add_to_changelog, only_username):
    ldap_connect()

    filt = None
    if only_username:
        filt = '(%s=%s)' % (ldap_attr('user_id'), only_username)

    import wato
    users      = wato.load_users()
    ldap_users = ldap_get_users()

    # Remove users which are controlled by this connector but can not be found in
    # LDAP anymore
    for user_id, user in users.items():
        if user.get('connector') == 'ldap' and user_id not in ldap_users:
            del users[user_id] # remove the user
            wato.log_pending(wato.SYNCRESTART, None, "edit-users", _("LDAP Connector: Removed user %s" % user_id))

    for user_id, ldap_user in ldap_users.items():
        if user_id in users:
            user = users[user_id].copy()
            mode_create = False
        else:
            user = new_user_template('ldap')
            mode_create = True

        # Skip all users not controlled by this connector
        if user.get('connector') != 'ldap':
            continue

        # Gather config from convert functions of plugins
        for key in config.ldap_active_plugins:
            user.update(ldap_attribute_plugins[key]['convert'](user_id, ldap_user))

        if not mode_create and user == users[user_id]:
            continue # no modification. Skip this user.

        users[user_id] = user # Update the user record

        if mode_create:
            wato.log_pending(wato.SYNCRESTART, None, "edit-users", _("LDAP Connector: Created user %s" % user_id))
        else:
            wato.log_pending(wato.SYNCRESTART, None, "edit-users", _("LDAP Connector: Modified user %s" % user_id))

    wato.save_users(users)

# Calculates the attributes of the users which are locked for users managed
# by this connector
def ldap_locked():
    locked = set([ 'password' ]) # This attributes are locked in all cases!
    for key in config.ldap_active_plugins:
        locked.update(ldap_attribute_plugins[key]['set_attributes'])
    return list(locked)

multisite_user_connectors.append({
    'id':    'ldap',
    'title': _('LDAP (AD, OpenLDAP)'),

    'login':             ldap_login,
    'sync':              ldap_sync,
    'locked_attributes': ldap_locked,
})
