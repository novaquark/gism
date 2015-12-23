#!/usr/bin/python

import re
import string
import os
import platform
import argparse
import datetime
from distutils.spawn import find_executable as which


#FIXME: test runtime dependancies
#FIXME: add git support for initial checkout (no updates yes)
#FIXME: add an svn mode to force the local copy to be an exact replica of the remote one

def touch(path):
    with open(path, 'a'):
        os.utime(path, None)


hostOS = platform.system()
rsync = ""

def setOS():
    global hostOS, rsync # Mmmm
    print("Detected " + hostOS + " os")
    if hostOS == "Windows" or re.match("CYGWIN_NT", hostOS):
        hostOS = "win"
        rsync = "rsync.exe"
    elif hostOS == "Linux":
        hostOS = "linux"
        rsync = "rsync"
    else:
        print("Unsupported OS")
        exit(1)

setOS()
        
def svnCheckout(url, revision, destination, cache=""):
    """ The cache system improves performance of initial branch builds on continuous integration"""
    svnDestination = destination
    ret = 0
    useCache=False
    if cache:
        if(not os.access(destination+"/"+".svn", os.R_OK)):
            svnDestination = cache + "/" + re.sub("[.][.]/","/", destination)
            if not os.access(svnDestination, os.R_OK):
                os.makedirs(svnDestination)
            if not which(rsync):
                print("need rsync in the PATH to use the cache")
                exit(1)
            useCache=True
            print("Will use cache since this is an initial checkout")
        else:
            useCache=False
            print("Will not use cache, checkout has already been done")

    #cleanup in case the previous run failed
    os.system("svn cleanup " + svnDestination)

    # checkout to the final dest or to the cache
    if revision != "trunk":
        revParam = "-r " + revision
        revURL = "@"+revision
    else:
        revParam = ""
        revURL = ""

    if(not os.access(destination+"/"+".svn", os.R_OK)):
        print("svn checkout: " + url + " (rev " + revision + ") -> " + svnDestination)
        ret = os.system("svn checkout " + url + revURL + " " + svnDestination)
    else:
        print("svn update: " + url + " (rev " + revision + ") -> " + svnDestination)
        # ignore conflicts
        # FIXME: should be an option
        #ret += os.system("svn resolve --accept theirs-full -R " + svnDestination)
        #ret += os.system("svn switch " + url + revURL + " " + svnDestination)
        #ret += os.system("svn update --accept theirs-full --force " + revParam + " " + svnDestination)
        ret += os.system("svn update " + revParam + " " + svnDestination)

    if(ret != 0):
        print("Error updating SVN, will use fallback")
        os.rename(svnDestination, svnDestination + '.bak.'+datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
        ret = os.system("svn checkout " + url + revURL + " " + svnDestination)

        if(ret != 0):
            print("Fallback failed, exit")
            exit(1)

    if useCache:
        print("Copy the cache to the final destination")
        if not os.access(destination, os.R_OK):
            os.makedirs(destination)
        if hostOS == "win":
            command = rsync + " -avW --no-compress --chmod=ug=rwX \"" + \
                      re.sub(r"[\/\\ ]+","/",re.sub("([A-Za-z]):","/cygdrive/\\1",svnDestination)) + "/\" " + destination + "/"
        else:
            command = "cp -al " + svnDestination + " " + destination
        print("execute " + command)
        ret += os.system(command)
    return ret

commentRE = re.compile('^#')
svnRE = re.compile('^http://')
gitRE = re.compile('^ssh://')

def update(cache="", modules="modules.txt", dest=".", buildonly=False, runtimeonly=False, recursive=False):

    lines = [line.strip() for line in open(modules) if line.strip()]
    previousDir = os.getcwd()
    os.chdir(dest)

    for line in lines:
        if not commentRE.match(line):
            platform, url, destination, revision = line.split()
            if ((hostOS in platform) or ('all' in platform)) and \
               ( \
                ((not buildonly) and (not 'buildonly' in platform)) \
                or \
                ((buildonly ) and (not 'runtimeonly' in platform)) \
               ):
                revision = revision.strip()
                if svnRE.match(url):
                    retvalue = svnCheckout(url, revision, destination, cache)
                    if retvalue != 0:
                        print("to login on SVN ask sysadmin for login and password\n")
                        exit(retvalue)
                else:
                    print("Unsupported URL scheme at the moment\n")

    if(recursive and os.access(destination+'/'+modules, os.R_OK)):
        os.chdir(destination)
        update(cache=cache, modules=modules, dest=".", buildonly=buildonly, runtimeonly=runtimeonly)

    os.chdir(previousDir)


if __name__ == '__main__':

    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('--cache', help='Specify a PATH to cache svn (for continous integration)')
    parser.add_argument('--buildonly', help='Do not checkout runtime only dependencies', action='store_true')
    parser.add_argument('--modules', default="modules.txt", help='Specify a modules file')
    parser.add_argument('--dest', default=".", help='Specify a destination PATH for the whole treem')
    parser.add_argument('--recursive', help='find modules.txt recursively and update them', action='store_true')

    args, unknown = parser.parse_known_args()

    if unknown:
        print(__file__ + " warning, ignore unknown options: " )
        for option in unknown:
            print(option)

    update(cache=args.cache, buildonly=args.buildonly, modules=args.modules, dest=args.dest, recursive=args.recursive)

