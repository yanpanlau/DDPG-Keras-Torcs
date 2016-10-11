#!/usr/bin/env python
# snakeoil.py
# Chris X Edwards <snakeoil@xed.ch>
# Snake Oil is a Python library for interfacing with a TORCS
# race car simulator which has been patched with the server
# extentions used in the Simulated Car Racing competitions.
# http://scr.geccocompetitions.com/
#
# To use it, you must import it and create a "drive()" function.
# This will take care of option handling and server connecting, etc.
# To see how to write your own client do something like this which is
# a complete working client:
# /-----------------------------------------------\
# |#!/usr/bin/python                              |
# |import snakeoil                                |
# |if __name__ == "__main__":                     |
# |    C= snakeoil.Client()                       |
# |    for step in xrange(C.maxSteps,0,-1):       |
# |        C.get_servers_input()                  |
# |        snakeoil.drive_example(C)              |
# |        C.respond_to_server()                  |
# |    C.shutdown()                               |
# \-----------------------------------------------/
# This should then be a full featured client. The next step is to
# replace 'snakeoil.drive_example()' with your own. There is a
# dictionary which holds various option values (see `default_options`
# variable for all the details) but you probably only need a few
# things from it. Mainly the `trackname` and `stage` are important
# when developing a strategic bot.
#
# This dictionary also contains a ServerState object
# (key=S) and a DriverAction object (key=R for response). This allows
# you to get at all the information sent by the server and to easily
# formulate your reply. These objects contain a member dictionary "d"
# (for data dictionary) which contain key value pairs based on the
# server's syntax. Therefore, you can read the following:
#    angle, curLapTime, damage, distFromStart, distRaced, focus,
#    fuel, gear, lastLapTime, opponents, racePos, rpm,
#    speedX, speedY, speedZ, track, trackPos, wheelSpinVel, z
# The syntax specifically would be something like:
#    X= o[S.d['tracPos']]
# And you can set the following:
#    accel, brake, clutch, gear, steer, focus, meta
# The syntax is:
#     o[R.d['steer']]= X
# Note that it is 'steer' and not 'steering' as described in the manual!
# All values should be sensible for their type, including lists being lists.
# See the SCR manual or http://xed.ch/help/torcs.html for details.
#
# If you just run the snakeoil.py base library itself it will implement a
# serviceable client with a demonstration drive function that is
# sufficient for getting around most tracks.
# Try `snakeoil.py --help` to get started.

# for Python3-based torcs python robot client
from __future__ import division
from __future__ import absolute_import
import socket
import sys
import getopt
import os
import time
PI= 3.14159265359

data_size = 2**17

# Initialize help messages
ophelp=  u'Options:\n'
ophelp+= u' --host, -H <host>    TORCS server host. [localhost]\n'
ophelp+= u' --port, -p <port>    TORCS port. [3001]\n'
ophelp+= u' --id, -i <id>        ID for server. [SCR]\n'
ophelp+= u' --steps, -m <#>      Maximum simulation steps. 1 sec ~ 50 steps. [100000]\n'
ophelp+= u' --episodes, -e <#>   Maximum learning episodes. [1]\n'
ophelp+= u' --track, -t <track>  Your name for this track. Used for learning. [unknown]\n'
ophelp+= u' --stage, -s <#>      0=warm up, 1=qualifying, 2=race, 3=unknown. [3]\n'
ophelp+= u' --debug, -d          Output full telemetry.\n'
ophelp+= u' --help, -h           Show this help.\n'
ophelp+= u' --version, -v        Show current version.'
usage= u'Usage: %s [ophelp [optargs]] \n' % sys.argv[0]
usage= usage + ophelp
version= u"20130505-2"

def clip(v,lo,hi):
    if v<lo: return lo
    elif v>hi: return hi
    else: return v

def bargraph(x,mn,mx,w,c=u'X'):
    u'''Draws a simple asciiart bar graph. Very handy for
    visualizing what's going on with the data.
    x= Value from sensor, mn= minimum plottable value,
    mx= maximum plottable value, w= width of plot in chars,
    c= the character to plot with.'''
    if not w: return u'' # No width!
    if x<mn: x= mn      # Clip to bounds.
    if x>mx: x= mx      # Clip to bounds.
    tx= mx-mn # Total real units possible to show on graph.
    if tx<=0: return u'backwards' # Stupid bounds.
    upw= tx/float(w) # X Units per output char width.
    if upw<=0: return u'what?' # Don't let this happen.
    negpu, pospu, negnonpu, posnonpu= 0,0,0,0
    if mn < 0: # Then there is a negative part to graph.
        if x < 0: # And the plot is on the negative side.
            negpu= -x + min(0,mx)
            negnonpu= -mn + x
        else: # Plot is on pos. Neg side is empty.
            negnonpu= -mn + min(0,mx) # But still show some empty neg.
    if mx > 0: # There is a positive part to the graph
        if x > 0: # And the plot is on the positive side.
            pospu= x - max(0,mn)
            posnonpu= mx - x
        else: # Plot is on neg. Pos side is empty.
            posnonpu= mx - max(0,mn) # But still show some empty pos.
    nnc= int(negnonpu/upw)*u'-'
    npc= int(negpu/upw)*c
    ppc= int(pospu/upw)*c
    pnc= int(posnonpu/upw)*u'_'
    return u'[%s]' % (nnc+npc+ppc+pnc)

class Client(object):
    def __init__(self,H=None,p=None,i=None,e=None,t=None,s=None,d=None,vision=False):
        # If you don't like the option defaults,  change them here.
        self.vision = vision

        self.host= u'localhost'
        self.port= 3001
        self.sid= u'SCR'
        self.maxEpisodes=1 # "Maximum number of learning episodes to perform"
        self.trackname= u'unknown'
        self.stage= 3 # 0=Warm-up, 1=Qualifying 2=Race, 3=unknown <Default=3>
        self.debug= False
        self.maxSteps= 100000  # 50steps/second
        self.parse_the_command_line()
        if H: self.host= H
        if p: self.port= p
        if i: self.sid= i
        if e: self.maxEpisodes= e
        if t: self.trackname= t
        if s: self.stage= s
        if d: self.debug= d
        self.S= ServerState()
        self.R= DriverAction()
        self.setup_connection()

    def setup_connection(self):
        # == Set Up UDP Socket ==
        try:
            self.so= socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except socket.error, emsg:
            print u'Error: Could not create socket...'
            sys.exit(-1)
        # == Initialize Connection To Server ==
        self.so.settimeout(1)

        n_fail = 5
        while True:
            # This string establishes track sensor angles! You can customize them.
            #a= "-90 -75 -60 -45 -30 -20 -15 -10 -5 0 5 10 15 20 30 45 60 75 90"
            # xed- Going to try something a bit more aggressive...
            a= u"-45 -19 -12 -7 -4 -2.5 -1.7 -1 -.5 0 .5 1 1.7 2.5 4 7 12 19 45"

            initmsg=u'%s(init %s)' % (self.sid,a)

            try:
                self.so.sendto(initmsg.encode(), (self.host, self.port))
            except socket.error, emsg:
                sys.exit(-1)
            sockdata= unicode()
            try:
                sockdata,addr= self.so.recvfrom(data_size)
                sockdata = sockdata.decode(u'utf-8')
            except socket.error, emsg:
                print u"Waiting for server on %d............" % self.port
                print u"Count Down : " + unicode(n_fail)
                if n_fail < 0:
                    print u"relaunch torcs"
                    os.system(u'pkill torcs')
                    time.sleep(1.0)
                    if self.vision is False:
                        os.system(u'torcs -nofuel -nodamage -nolaptime &')
                    else:
                        os.system(u'torcs -nofuel -nodamage -nolaptime -vision &')

                    time.sleep(1.0)
                    os.system(u'sh autostart.sh')
                    n_fail = 5
                n_fail -= 1

            identify = u'***identified***'
            if identify in sockdata:
                print u"Client connected on %d.............." % self.port
                break

    def parse_the_command_line(self):
        try:
            (opts, args) = getopt.getopt(sys.argv[1:], u'H:p:i:m:e:t:s:dhv',
                       [u'host=',u'port=',u'id=',u'steps=',
                        u'episodes=',u'track=',u'stage=',
                        u'debug',u'help',u'version'])
        except getopt.error, why:
            print u'getopt error: %s\n%s' % (why, usage)
            sys.exit(-1)
        try:
            for opt in opts:
                if opt[0] == u'-h' or opt[0] == u'--help':
                    print usage
                    sys.exit(0)
                if opt[0] == u'-d' or opt[0] == u'--debug':
                    self.debug= True
                if opt[0] == u'-H' or opt[0] == u'--host':
                    self.host= opt[1]
                if opt[0] == u'-i' or opt[0] == u'--id':
                    self.sid= opt[1]
                if opt[0] == u'-t' or opt[0] == u'--track':
                    self.trackname= opt[1]
                if opt[0] == u'-s' or opt[0] == u'--stage':
                    self.stage= int(opt[1])
                if opt[0] == u'-p' or opt[0] == u'--port':
                    self.port= int(opt[1])
                if opt[0] == u'-e' or opt[0] == u'--episodes':
                    self.maxEpisodes= int(opt[1])
                if opt[0] == u'-m' or opt[0] == u'--steps':
                    self.maxSteps= int(opt[1])
                if opt[0] == u'-v' or opt[0] == u'--version':
                    print u'%s %s' % (sys.argv[0], version)
                    sys.exit(0)
        except ValueError, why:
            print u'Bad parameter \'%s\' for option %s: %s\n%s' % (
                                       opt[1], opt[0], why, usage)
            sys.exit(-1)
        if len(args) > 0:
            print u'Superflous input? %s\n%s' % (u', '.join(args), usage)
            sys.exit(-1)

    def get_servers_input(self):
        u'''Server's input is stored in a ServerState object'''
        if not self.so: return
        sockdata= unicode()

        while True:
            try:
                # Receive server data
                sockdata,addr= self.so.recvfrom(data_size)
                sockdata = sockdata.decode(u'utf-8')
            except socket.error, emsg:
                print u'.',
                #print "Waiting for data on %d.............." % self.port
            if u'***identified***' in sockdata:
                print u"Client connected on %d.............." % self.port
                continue
            elif u'***shutdown***' in sockdata:
                print ((u"Server has stopped the race on %d. "+
                        u"You were in %d place.") %
                        (self.port,self.S.d[u'racePos']))
                self.shutdown()
                return
            elif u'***restart***' in sockdata:
                # What do I do here?
                print u"Server has restarted the race on %d." % self.port
                # I haven't actually caught the server doing this.
                self.shutdown()
                return
            elif not sockdata: # Empty?
                continue       # Try again.
            else:
                self.S.parse_server_str(sockdata)
                if self.debug:
                    sys.stderr.write(u"\x1b[2J\x1b[H") # Clear for steady output.
                    print self.S
                break # Can now return from this function.

    def respond_to_server(self):
        if not self.so: return
        try:
            message = repr(self.R)
            self.so.sendto(message.encode(), (self.host, self.port))
        except socket.error, emsg:
            print u"Error sending to server: %s Message %s" % (emsg[1],unicode(emsg[0]))
            sys.exit(-1)
        if self.debug: print self.R.fancyout()
        # Or use this for plain output:
        #if self.debug: print self.R

    def shutdown(self):
        if not self.so: return
        print (u"Race terminated or %d steps elapsed. Shutting down %d."
               % (self.maxSteps,self.port))
        self.so.close()
        self.so = None
        #sys.exit() # No need for this really.

class ServerState(object):
    u'''What the server is reporting right now.'''
    def __init__(self):
        self.servstr= unicode()
        self.d= dict()

    def parse_server_str(self, server_string):
        u'''Parse the server string.'''
        self.servstr= server_string.strip()[:-1]
        sslisted= self.servstr.strip().lstrip(u'(').rstrip(u')').split(u')(')
        for i in sslisted:
            w= i.split(u' ')
            self.d[w[0]]= destringify(w[1:])

    def __repr__(self):
        # Comment the next line for raw output:
        return self.fancyout()
        # -------------------------------------
        out= unicode()
        for k in sorted(self.d):
            strout= unicode(self.d[k])
            if type(self.d[k]) is list:
                strlist= [unicode(i) for i in self.d[k]]
                strout= u', '.join(strlist)
            out+= u"%s: %s\n" % (k,strout)
        return out

    def fancyout(self):
        u'''Specialty output for useful ServerState monitoring.'''
        out= unicode()
        sensors= [ # Select the ones you want in the order you want them.
        #'curLapTime',
        #'lastLapTime',
        u'stucktimer',
        #'damage',
        #'focus',
        u'fuel',
        #'gear',
        u'distRaced',
        u'distFromStart',
        #'racePos',
        u'opponents',
        u'wheelSpinVel',
        u'z',
        u'speedZ',
        u'speedY',
        u'speedX',
        u'targetSpeed',
        u'rpm',
        u'skid',
        u'slip',
        u'track',
        u'trackPos',
        u'angle',
        ]

        #for k in sorted(self.d): # Use this to get all sensors.
        for k in sensors:
            if type(self.d.get(k)) is list: # Handle list type data.
                if k == u'track': # Nice display for track sensors.
                    strout= unicode()
                 #  for tsensor in self.d['track']:
                 #      if   tsensor >180: oc= '|'
                 #      elif tsensor > 80: oc= ';'
                 #      elif tsensor > 60: oc= ','
                 #      elif tsensor > 39: oc= '.'
                 #      #elif tsensor > 13: oc= chr(int(tsensor)+65-13)
                 #      elif tsensor > 13: oc= chr(int(tsensor)+97-13)
                 #      elif tsensor >  3: oc= chr(int(tsensor)+48-3)
                 #      else: oc= '_'
                 #      strout+= oc
                 #  strout= ' -> '+strout[:9] +' ' + strout[9] + ' ' + strout[10:]+' <-'
                    raw_tsens= [u'%.1f'%x for x in self.d[u'track']]
                    strout+= u' '.join(raw_tsens[:9])+u'_'+raw_tsens[9]+u'_'+u' '.join(raw_tsens[10:])
                elif k == u'opponents': # Nice display for opponent sensors.
                    strout= unicode()
                    for osensor in self.d[u'opponents']:
                        if   osensor >190: oc= u'_'
                        elif osensor > 90: oc= u'.'
                        elif osensor > 39: oc= unichr(int(osensor/2)+97-19)
                        elif osensor > 13: oc= unichr(int(osensor)+65-13)
                        elif osensor >  3: oc= unichr(int(osensor)+48-3)
                        else: oc= u'?'
                        strout+= oc
                    strout= u' -> '+strout[:18] + u' ' + strout[18:]+u' <-'
                else:
                    strlist= [unicode(i) for i in self.d[k]]
                    strout= u', '.join(strlist)
            else: # Not a list type of value.
                if k == u'gear': # This is redundant now since it's part of RPM.
                    gs= u'_._._._._._._._._'
                    p= int(self.d[u'gear']) * 2 + 2  # Position
                    l= u'%d'%self.d[u'gear'] # Label
                    if l==u'-1': l= u'R'
                    if l==u'0':  l= u'N'
                    strout= gs[:p]+ u'(%s)'%l + gs[p+3:]
                elif k == u'damage':
                    strout= u'%6.0f %s' % (self.d[k], bargraph(self.d[k],0,10000,50,u'~'))
                elif k == u'fuel':
                    strout= u'%6.0f %s' % (self.d[k], bargraph(self.d[k],0,100,50,u'f'))
                elif k == u'speedX':
                    cx= u'X'
                    if self.d[k]<0: cx= u'R'
                    strout= u'%6.1f %s' % (self.d[k], bargraph(self.d[k],-30,300,50,cx))
                elif k == u'speedY': # This gets reversed for display to make sense.
                    strout= u'%6.1f %s' % (self.d[k], bargraph(self.d[k]*-1,-25,25,50,u'Y'))
                elif k == u'speedZ':
                    strout= u'%6.1f %s' % (self.d[k], bargraph(self.d[k],-13,13,50,u'Z'))
                elif k == u'z':
                    strout= u'%6.3f %s' % (self.d[k], bargraph(self.d[k],.3,.5,50,u'z'))
                elif k == u'trackPos': # This gets reversed for display to make sense.
                    cx=u'<'
                    if self.d[k]<0: cx= u'>'
                    strout= u'%6.3f %s' % (self.d[k], bargraph(self.d[k]*-1,-1,1,50,cx))
                elif k == u'stucktimer':
                    if self.d[k]:
                        strout= u'%3d %s' % (self.d[k], bargraph(self.d[k],0,300,50,u"'"))
                    else: strout= u'Not stuck!'
                elif k == u'rpm':
                    g= self.d[u'gear']
                    if g < 0:
                        g= u'R'
                    else:
                        g= u'%1d'% g
                    strout= bargraph(self.d[k],0,10000,50,g)
                elif k == u'angle':
                    asyms= [
                          u"  !  ", u".|'  ", u"./'  ", u"_.-  ", u".--  ", u"..-  ",
                          u"---  ", u".__  ", u"-._  ", u"'-.  ", u"'\.  ", u"'|.  ",
                          u"  |  ", u"  .|'", u"  ./'", u"  .-'", u"  _.-", u"  __.",
                          u"  ---", u"  --.", u"  -._", u"  -..", u"  '\.", u"  '|."  ]
                    rad= self.d[k]
                    deg= int(rad*180/PI)
                    symno= int(.5+ (rad+PI) / (PI/12) )
                    symno= symno % (len(asyms)-1)
                    strout= u'%5.2f %3d (%s)' % (rad,deg,asyms[symno])
                elif k == u'skid': # A sensible interpretation of wheel spin.
                    frontwheelradpersec= self.d[u'wheelSpinVel'][0]
                    skid= 0
                    if frontwheelradpersec:
                        skid= .5555555555*self.d[u'speedX']/frontwheelradpersec - .66124
                    strout= bargraph(skid,-.05,.4,50,u'*')
                elif k == u'slip': # A sensible interpretation of wheel spin.
                    frontwheelradpersec= self.d[u'wheelSpinVel'][0]
                    slip= 0
                    if frontwheelradpersec:
                        slip= ((self.d[u'wheelSpinVel'][2]+self.d[u'wheelSpinVel'][3]) -
                              (self.d[u'wheelSpinVel'][0]+self.d[u'wheelSpinVel'][1]))
                    strout= bargraph(slip,-5,150,50,u'@')
                else:
                    strout= unicode(self.d[k])
            out+= u"%s: %s\n" % (k,strout)
        return out

class DriverAction(object):
    u'''What the driver is intending to do (i.e. send to the server).
    Composes something like this for the server:
    (accel 1)(brake 0)(gear 1)(steer 0)(clutch 0)(focus 0)(meta 0) or
    (accel 1)(brake 0)(gear 1)(steer 0)(clutch 0)(focus -90 -45 0 45 90)(meta 0)'''
    def __init__(self):
       self.actionstr= unicode()
       # "d" is for data dictionary.
       self.d= { u'accel':0.2,
                   u'brake':0,
                  u'clutch':0,
                    u'gear':1,
                   u'steer':0,
                   u'focus':[-90,-45,0,45,90],
                    u'meta':0
                    }

    def clip_to_limits(self):
        u"""There pretty much is never a reason to send the server
        something like (steer 9483.323). This comes up all the time
        and it's probably just more sensible to always clip it than to
        worry about when to. The "clip" command is still a snakeoil
        utility function, but it should be used only for non standard
        things or non obvious limits (limit the steering to the left,
        for example). For normal limits, simply don't worry about it."""
        self.d[u'steer']= clip(self.d[u'steer'], -1, 1)
        self.d[u'brake']= clip(self.d[u'brake'], 0, 1)
        self.d[u'accel']= clip(self.d[u'accel'], 0, 1)
        self.d[u'clutch']= clip(self.d[u'clutch'], 0, 1)
        if self.d[u'gear'] not in [-1, 0, 1, 2, 3, 4, 5, 6]:
            self.d[u'gear']= 0
        if self.d[u'meta'] not in [0,1]:
            self.d[u'meta']= 0
        if type(self.d[u'focus']) is not list or min(self.d[u'focus'])<-180 or max(self.d[u'focus'])>180:
            self.d[u'focus']= 0

    def __repr__(self):
        self.clip_to_limits()
        out= unicode()
        for k in self.d:
            out+= u'('+k+u' '
            v= self.d[k]
            if not type(v) is list:
                out+= u'%.3f' % v
            else:
                out+= u' '.join([unicode(x) for x in v])
            out+= u')'
        return out
        return out+u'\n'

    def fancyout(self):
        u'''Specialty output for useful monitoring of bot's effectors.'''
        out= unicode()
        od= self.d.copy()
        od.pop(u'gear',u'') # Not interesting.
        od.pop(u'meta',u'') # Not interesting.
        od.pop(u'focus',u'') # Not interesting. Yet.
        for k in sorted(od):
            if k == u'clutch' or k == u'brake' or k == u'accel':
                strout=u''
                strout= u'%6.3f %s' % (od[k], bargraph(od[k],0,1,50,k[0].upper()))
            elif k == u'steer': # Reverse the graph to make sense.
                strout= u'%6.3f %s' % (od[k], bargraph(od[k]*-1,-1,1,50,u'S'))
            else:
                strout= unicode(od[k])
            out+= u"%s: %s\n" % (k,strout)
        return out

# == Misc Utility Functions
def destringify(s):
    u'''makes a string into a value or a list of strings into a list of
    values (if possible)'''
    if not s: return s
    if type(s) is unicode:
        try:
            return float(s)
        except ValueError:
            print u"Could not find a value in %s" % s
            return s
    elif type(s) is list:
        if len(s) < 2:
            return destringify(s[0])
        else:
            return [destringify(i) for i in s]

def drive_example(c):
    u'''This is only an example. It will get around the track but the
    correct thing to do is write your own `drive()` function.'''
    S,R= c.S.d,c.R.d
    target_speed=1000

    # Steer To Corner
    R[u'steer']= S[u'angle']*10 / PI
    # Steer To Center
    R[u'steer']-= S[u'trackPos']*.10

    # Throttle Control
    if S[u'speedX'] < target_speed - (R[u'steer']*50):
        R[u'accel']+= .01
    else:
        R[u'accel']-= .01
    if S[u'speedX']<10:
       R[u'accel']+= 1/(S[u'speedX']+.1)

    # Traction Control System
    if ((S[u'wheelSpinVel'][2]+S[u'wheelSpinVel'][3]) -
       (S[u'wheelSpinVel'][0]+S[u'wheelSpinVel'][1]) > 5):
       R[u'accel']-= .2

    # Automatic Transmission
    R[u'gear']=1
    if S[u'speedX']>50:
        R[u'gear']=2
    if S[u'speedX']>80:
        R[u'gear']=3
    if S[u'speedX']>110:
        R[u'gear']=4
    if S[u'speedX']>140:
        R[u'gear']=5
    if S[u'speedX']>170:
        R[u'gear']=6
    return

# ================ MAIN ================
if __name__ == u"__main__":
    C= Client(p=3101)
    for step in xrange(C.maxSteps,0,-1):
        C.get_servers_input()
        drive_example(C)
        C.respond_to_server()
    C.shutdown()
