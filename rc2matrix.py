#!/usr/bin/python3

import argparse
import sys
import os
import pprint as ppprint
import json
import requests
from datetime import datetime
import re


# globals
# inputs = "inputs/"
roomsfile = "rocketchat_room.json"
usersfile = "users.json"
histfile = "rocketchat_message.json"
verbose = False

def terminal_size():
    import fcntl
    import termios
    import struct
    h, w, hp, wp = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0)))
    return w, h

def pprint(name, data):
    if verbose:
        w, h = terminal_size()
        pp = ppprint.PrettyPrinter(indent=2, width=w)
        print(name + ": ")
        pp.pprint(data)
        print("\n\n")

def vprint(data):
    if verbose:
        print(str(data))
        print("\n\n")

def createArgParser():
    parser = argparse.ArgumentParser(description='Launches RC2Matrix migration')
    parser.add_argument("-i", type=str, help='inputs folder, defaults to inputs/', dest="inputs", default="inputs/")
    parser.add_argument("-n", type=str, help='Matrix server', dest="hostname", default="localhost")
    parser.add_argument("-u", type=str, help='Admin username', dest="username", default="admin")
    parser.add_argument("-p", type=str, help='Admin password', dest="password", default="password")
    parser.add_argument("-t", type=str, help='Admin token', dest="token", default=None )
    parser.add_argument("-a", type=str, help='Application token', dest="apptoken", default=None )
    parser.add_argument("-v", help='verbose', dest="verbose", action="store_true")

    return parser

def format_message(raw, ancestor=None):
    if ancestor is not None:
        return relate_message(raw, ancestor)

    formatted = raw
    formatted = re.sub("```(.+)```", "<code>\\1</code>", formatted)
    formatted = re.sub("`(.+)`", "<code>\\1</code>", formatted)
    if formatted == raw:
        api_params = {'msgtype': 'm.text', 'body': raw}
    else:
        api_params = {'msgtype': 'm.text', 'body': raw,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted}

    return api_params

def relate_message(raw, ancestor):
    api_params = {'msgtype': 'm.text', 'body': raw,
        "m.relates_to": {
            "m.in_reply_to": {
                "event_id": ancestor
                }
            }
        }

    return api_params

if __name__ == '__main__':
    parser = createArgParser()
    args = parser.parse_args()
    verbose = args.verbose

    if (verbose):
        print("Arguments are: ", args)

    api_base = "https://" + args.hostname + "/"
    # Connect to matrix
    if args.token is None: # create a token
        api_endpoint = api_base + "_matrix/client/v3/login"
        api_params = {"type": "m.login.password","user": args.username,"password": args.password,"device_id": "rc2m"}
        response = requests.post(api_endpoint, json=api_params)
        vprint(response.json())
        if response.status_code == 200:
            token=response.json()["access_token"]
            vprint("Token is " + token)
            exit(0)
        else:
            exit("failed to connect")

    api_headers_admin =  {"Authorization":"Bearer " + args.token}
    api_headers_as =  {"Authorization":"Bearer " + args.apptoken}

    # Rooms
    roomnames = {}
    roomids = {}
    with open(args.inputs + roomsfile, 'r') as jsonfile:
        for line in jsonfile:
            currentroom = json.loads(line)
            pprint("current room", currentroom)
            api_endpoint = api_base + "_matrix/client/v3/createRoom"
            if currentroom['t'] == 'd': # DM
                roomname="ZZ-" + "-".join(currentroom['usernames'])
                api_params = {"visibility": "private", "name": roomname, "join_rules": "invite", 'is_direct': 'true'}
            elif currentroom['t'] == 'c': # chat
                roomname=currentroom['name']
                if 'announcement' in currentroom:
                    api_params = {"visibility": "public", "name": roomname, "room_alias_name": roomname, 'topic': currentroom['announcement']}
                else:
                    api_params = {"visibility": "public", "name": roomname, "room_alias_name": roomname}
            elif currentroom['t'] == 'p': # private chat
                roomname=currentroom['name']
                if 'announcement' in currentroom:
                    api_params = {"visibility": "private", "join_rules": "invite", "name": roomname, "room_alias_name": roomname, 'topic': currentroom['announcement']}
                else:
                    api_params = {"visibility": "private", "join_rules": "invite", "name": roomname, "room_alias_name": roomname}
            else:
                exit("Unsupported room type : " + currentroom['t'])
            response = requests.post(api_endpoint, json=api_params, headers=api_headers_admin)
            vprint(response.json())
            if response.status_code == 200: # created successfully
                roomids[currentroom['_id']] = response.json()['room_id']
            elif response.status_code == 400 and response.json()['errcode'] == 'M_ROOM_IN_USE': # already existing
                api_endpoint = api_base + "/_matrix/client/v3/publicRooms"
                api_endpoint = api_base + "/_synapse/admin/v1/rooms?search_term=" + roomname
                #api_params = {"filter": { "generic_search_term": roomname}}
                response = requests.get(api_endpoint, headers=api_headers_admin)
                vprint(response.json())
                roomids[currentroom['_id']] = response.json()['rooms'][0]['room_id']
            else:
                exit("Unsupported fail for room creation")
            # rooms.append(json.loads(line))

    pprint("room names", roomnames)
    pprint("room ids", roomids)

    # Users
    usernames = {}
    with open(args.inputs + usersfile, 'r') as jsonfile:
        for line in jsonfile:
            currentuser = json.loads(line)
            pprint("current user", currentuser)
            username=currentuser['username']
            usernames[currentuser['_id']] = username
            api_endpoint = api_base + "/_synapse/admin/v2/users/@" + username + ":" + args.hostname
            vprint(api_endpoint)
            api_params = {"admin": False}
            response = requests.put(api_endpoint, json=api_params, headers=api_headers_admin)
            vprint(response.json())

    pprint("user names", usernames)



    # Messages
    lastts = 0
    with open(args.inputs + histfile, 'r') as jsonfile:
        for line in jsonfile:
            currentmsg = json.loads(line)
            pprint("current message", currentmsg)
            if currentmsg['rid'] in roomids:
                tgtroom = roomids[currentmsg['rid']]
                tgtuser = "@" + currentmsg['u']['username'] + ":" + args.hostname
                dateTimeObj = datetime.fromisoformat(currentmsg['ts']['$date'])
                tgtts = int(dateTimeObj.timestamp()*1000)
                if tgtts < lastts: # messages are not sorted, bad things will happen
                    exit("Messages are not sorted, leaving...")
                lastts = tgtts
                # vprint("should be in room " + str(tgtroom))
                # Post message
                if 'file' in currentmsg: # File upload
                    # "file":{"_id":"u5Ga3vn36LCT9bfhW","name":"tree-736885_640.jpg","type":"image/jpeg"}
                    api_endpoint = api_base + "/_matrix/media/v3/upload?user_id=" + tgtuser + "&ts=" + str(tgtts)
                    api_params = {'filename': currentmsg['file']['name']}
                    #files = {'file': open('inputs/files/u5Ga3vn36LCT9bfhW', 'rb')}
                    api_headers_file = api_headers_as
                    api_headers_file['Content-Type'] = currentmsg['file']['type']
                    with open("inputs/files/" + currentmsg['file']['_id'], 'rb') as f:
                        response = requests.post(api_endpoint, json=api_params, headers=api_headers_file, data=f)
                    vprint(response.json())
                    mxcurl=response.json()['content_uri']
                    api_endpoint = api_base + "_matrix/client/v3/rooms/" + tgtroom + '/send/m.room.message?user_id=' + tgtuser + "&ts=" + str(tgtts) # ts, ?user_id=@_irc_user:example.org
                    api_params = {'msgtype': 'm.file', 'body': currentmsg['file']['name'], 'url': mxcurl}
                    response = requests.post(api_endpoint, json=api_params, headers=api_headers_as)
                    vprint(response.json())
                else: # standard message
                    api_endpoint = api_base + "_matrix/client/v3/rooms/" + tgtroom + '/send/m.room.message?user_id=' + tgtuser + "&ts=" + str(tgtts) # ts, ?user_id=@_irc_user:example.org
                    api_params = format_message(currentmsg['msg'])
                    response = requests.post(api_endpoint, json=api_params, headers=api_headers_as)
                    vprint(response.json())

                    if response.status_code == 403 and response.json()['errcode'] == 'M_FORBIDDEN': # not in the room
                        # Join room : invite then join
                        api_endpoint = api_base + "/_synapse/admin/v1/join/" + tgtroom
                        api_params = {'user_id': tgtuser}
                        response = requests.post(api_endpoint, json=api_params, headers=api_headers_admin)
                        vprint(response.json())
                        # api_endpoint = api_base + "_matrix/client/v3/rooms/" + tgtroom + '/invite'
                        # api_params = {'user_id': tgtuser}
                        # response = requests.post(api_endpoint, json=api_params, headers=api_headers_admin)
                        # vprint(response.json())
                        # api_endpoint = api_base + "_matrix/client/v3/rooms/" + tgtroom + '/join?user_id=' + tgtuser + "&ts=" + str(tgtts)
                        # api_params = {'msgtype': 'm.text', 'body': 'b' + currentmsg['msg']}
                        # response = requests.post(api_endpoint, json=api_params, headers=api_headers_as)
                        # vprint(response.json())

                        # Repost message
                        api_endpoint = api_base + "_matrix/client/v3/rooms/" + tgtroom + '/send/m.room.message?user_id=' + tgtuser + "&ts=" + str(tgtts) # ts, ?user_id=@_irc_user:example.org
                        api_params = format_message(currentmsg['msg'])
                        response = requests.post(api_endpoint, json=api_params, headers=api_headers_as)
                        vprint(response.json())

            else:
                vprint("not in a room")

# , "event_id": "$143273582443PhrSn:example.org", "origin_server_ts": 1432735824653,  "room_id": "!jEsUZKDJdhlrceRyVU:example.org", "sender": "@example:example.org", "type": "m.room.message", "unsigned": {    "age": 1234  }

#
#
# access_token = 'YOURveryLONGaccessTOKENhere'
# room_id = '!ZkngAyfszzfCqwNZUd:phys:phys.ethz.ch'
# url = 'https://matrix.phys.ethz.ch/_matrix/client/r0/rooms/' + room_id + '/send/m.room.message'
# headers = {'Authorization': ' '.join(['Bearer', access_token])}
# data = {
#     'body': 'hello matrix',
#     'format': 'org.matrix.custom.html',
#     'formatted_body': 'hello <b>matrix</b>',
#     'msgtype': 'm.text'
# }
#
# r = requests.post(url, json=data, headers=headers)


# {
#   "content": {
#     "body": "This is an example text message",
#     "format": "org.matrix.custom.html",
#     "formatted_body": "<b>This is an example text message</b>",
#     "msgtype": "m.text"
#   },
#   "event_id": "$143273582443PhrSn:example.org",
#   "origin_server_ts": 1432735824653,
#   "room_id": "!jEsUZKDJdhlrceRyVU:example.org",
#   "sender": "@example:example.org",
#   "type": "m.room.message",
#   "unsigned": {
#     "age": 1234
#   }
# }

# room types : https://developer.rocket.chat/reference/api/schema-definition/room
# message types : https://developer.rocket.chat/reference/api/schema-definition/message
