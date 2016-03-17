#!/usr/bin/python -u

import re
import string
import os
import platform
import sys
import argparse
import datetime
from distutils.spawn import find_executable as which
from subprocess import check_call, call

#FIXME: test runtime dependancies
#FIXME: add git support for initial checkout (no updates yes)
#FIXME: add an svn mode to force the local copy to be an exact replica of the remote one

def touch(path):
    with open(path, 'a'):
        os.utime(path, None)


hostOS = platform.system()
rsync = ""
git = ""
svnoptions = "--config-option config:miscellany:use-commit-times=yes"


def setOS():
    global hostOS, rsync, git # Mmmm
    print("Detected " + hostOS + " os")
    if hostOS == "Windows" or re.match("CYGWIN_NT", hostOS):
        hostOS = "win"
        rsync = "rsync.exe"
        git = "git.exe"
    elif hostOS == "Linux":
        hostOS = "linux"
        rsync = "rsync"
        git = "git"
    else:
        print("Unsupported OS")
        exit(1)

setOS()

def gitCheckout(url, destination):
    check_call([git, 'clone', url, destination])
    gitUpdate(destination)

def gitUpdate(path):
    pwd = os.getcwd()
    os.chdir(path)
    call([git, 'pull'])
    check_call([git, 'submodule', 'update', '--init', '--recursive'])
    os.chdir(pwd)

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
        print("svn checkout")
        ret = os.system("svn checkout " + svnoptions + " " + url + revURL + " " + svnDestination)
    else:
        print("svn update")
        # ignore conflicts
        # FIXME: should be an option
        #ret += os.system("svn resolve --accept theirs-full -R " + svnDestination)
        #ret += os.system("svn switch " + url + revURL + " " + svnDestination)
        #ret += os.system("svn update --accept theirs-full --force " + revParam + " " + svnDestination)
        ret += os.system("svn update " + svnoptions + " " + revParam + " " + svnDestination)

    if(ret != 0):
        print("Error updating SVN, will use fallback")
        os.rename(svnDestination, svnDestination + '.bak.'+datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
        ret = os.system("svn checkout " + svnoptions + " " + url + revURL + " " + svnDestination)

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
includeRE = re.compile('^include')


def update(cache="", modules="modules.txt", dest=".", buildonly=False, runtimeonly=False, recursive=False):
    lines = [line.strip() for line in open(modules) if line.strip()]
    previousDir = os.getcwd()
    os.chdir(dest)

    for line in lines:
        if not commentRE.match(line):
            print("\n## in " + os.getcwd())
            print("## " + "processing: " + line + " recursive=" + str(recursive) )
            platform, url, destination, revision = line.split()
            if ((hostOS in platform) or ('all' in platform)) and \
               ( \
                ((not buildonly) and (not 'buildonly' in platform)) \
                or \
                ((buildonly ) and (not 'runtimeonly' in platform)) \
               ):
                revision = revision.strip()
                doRecursion = recursive
                if svnRE.match(url):
                    retvalue = svnCheckout(url, revision, destination, cache)
                    if retvalue != 0:
                        print("to login on SVN ask sysadmin for login and password\n")
                        exit(retvalue)
                elif gitRE.match(url):
                    if os.access(destination+"/.git", os.R_OK):
                        gitUpdate(destination)
                    else:
                        gitCheckout(url, destination)
                elif includeRE.match(url):
                    pass
                else:
                    doRecursion = False
                    print("Unsupported URL scheme at the moment\n")
                    
                if(doRecursion):
                    pd = os.getcwd()
                    os.chdir(destination)
                    if (os.access("bootstrap.py", os.R_OK)):
                        print(">>> execute bootstrap.py in " + destination)
                        os.system("python bootstrap.py")
                        print("<<<")
                    elif (os.access(modules, os.R_OK)):
                        print(">>> execute modules.txt in " + destination)
                        update(cache=cache, modules=modules, dest=".", buildonly=buildonly,
                               runtimeonly=runtimeonly, recursive=recursive)
                        print("<<<")
                    os.chdir(pd)

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

