"""Bounded MPRIS calls to the verified unique bus owner of our own process."""
from check_mpv import Blocked

ROOT = 'org.mpris.MediaPlayer2'
PLAYER = ROOT + '.Player'
PATH = '/org/mpris/MediaPlayer2'


class Mpris:
    def __init__(self, address, pid, event):
        try:
            from gi.repository import Gio, GLib
        except ImportError as exc:
            raise Blocked('Python GObject/Gio is required for MPRIS; no automatic installation') from exc
        self.Gio, self.GLib = Gio, GLib
        try:
            self.bus = Gio.DBusConnection.new_for_address_sync(address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
        except GLib.Error as exc:
            raise Blocked('Session bus unavailable: ' + str(exc)) from exc
        self.pid, self.event, self.owner = pid, event, None

    def raw(self, dest, path, interface, method, params=None):
        try:
            result = self.bus.call_sync(dest,path,interface,method,params,None,
                self.Gio.DBusCallFlags.NO_AUTO_START,2000,None)
            return result.unpack()
        except self.GLib.Error as exc:
            raise Blocked('MPRIS '+method+': '+str(exc)) from exc

    def bus_call(self, method, signature=None, args=()):
        return self.raw('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus',method,
                        self.GLib.Variant(signature,args) if signature else None)

    def discover(self):
        for name in self.bus_call('ListNames')[0]:
            if not name.startswith(ROOT+'.'):
                continue
            try:
                owner=self.bus_call('GetNameOwner','(s)',(name,))[0]
                pid=self.bus_call('GetConnectionUnixProcessID','(s)',(owner,))[0]
            except Blocked:
                continue
            if pid == self.pid:
                self.owner=owner
                self.event('mpris_owner',service=name,unique_owner=owner,pid=pid)
                return True
        return False

    def assert_owned(self):
        if not self.owner or self.bus_call('GetConnectionUnixProcessID','(s)',(self.owner,))[0] != self.pid:
            raise Blocked('MPRIS owner is not the process started by this test')

    def get(self, key, interface=PLAYER):
        self.assert_owned()
        return self.raw(self.owner,PATH,'org.freedesktop.DBus.Properties','Get',
                        self.GLib.Variant('(ss)',(interface,key)))[0]

    def call(self, method, signature=None, args=(), interface=PLAYER):
        self.assert_owned()
        result=self.raw(self.owner,PATH,interface,method,
                        self.GLib.Variant(signature,args) if signature else None)
        self.event('mpris_call',method=method,interface=interface,args=list(args),owner=self.owner)
        return result

    def set(self, key, signature, value, interface=PLAYER):
        self.assert_owned()
        result=self.raw(self.owner,PATH,'org.freedesktop.DBus.Properties','Set',
            self.GLib.Variant('(ssv)',(interface,key,self.GLib.Variant(signature,value))))
        self.event('mpris_set',property=key,interface=interface,value=value,owner=self.owner)
        return result

    def close(self):
        self.bus.close_sync(None)

    def fullscreen(self, app):
        if app=='vlc':
            return self.get('Fullscreen',ROOT)
        self.assert_owned()
        description=self.raw(self.owner,'/org/gnome/Totem','org.gtk.Actions','Describe',
                             self.GLib.Variant('(s)',('fullscreen',)))[0]
        if not description[0] or len(description[2])!=1 or not isinstance(description[2][0],bool):
            raise Blocked('Totem fullscreen action/state unavailable')
        return description[2][0]

    def set_fullscreen(self, app, value):
        if app=='vlc':
            if not self.get('CanSetFullscreen',ROOT):
                raise Blocked('VLC does not expose fullscreen control')
            return self.set('Fullscreen','b',value,ROOT)
        if self.fullscreen(app)!=value:
            self.assert_owned()
            self.raw(self.owner,'/org/gnome/Totem','org.gtk.Actions','Activate',
                     self.GLib.Variant('(sava{sv})',('fullscreen',[],{})))
            self.event('gapplication_action',action_name='fullscreen',requested=value,owner=self.owner)
