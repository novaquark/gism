#!/usr/bin/python -u

import argparse
import datetime
import json
import os
import platform
import re
import string
import sys
from shutil import copyfile, rmtree
from distutils.spawn import find_executable as which
from subprocess import check_output, check_call
try:
    from urllib.error import HTTPError
    from urllib.request import urlopen
    from urllib.parse import urlparse
except ImportError:
    from urllib2 import urlopen, HTTPError
    from urlparse import urlsplit as urlparse
import xml.etree.ElementTree as etree

class COLORS:
    PINK = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    DEFAULT = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def doNotUseColors():
    COLORS.PINK = ''
    COLORS.BLUE = ''
    COLORS.GREEN = ''
    COLORS.YELLOW = ''
    COLORS.RED = ''
    COLORS.DEFAULT = ''
    COLORS.BOLD = ''
    COLORS.UNDERLINE = ''

#FIXME: test runtime dependencies
#FIXME: add git support for initial checkout (no updates yes)

def del_rw(action, name, exc):
    import stat
    os.chmod(name, stat.S_IWRITE)
    os.remove(name)

def uprint(line):
    print(line)
    sys.stdout.flush()

def runDisplayCommand(cmd, use_check_call=False):
    uprint(COLORS.YELLOW + cmd + COLORS.DEFAULT)
    if use_check_call:
        return check_call(cmd)
    else:
        return os.system(cmd)


hostOS = platform.system()
rsync = ""
git = ""
svnoptions = "--no-auth-cache"

def setOS():
    global hostOS, rsync, git # Mmmm
    if hostOS == "Windows" or re.match("CYGWIN_NT", hostOS):
        hostOS = "win"
        rsync = "rsync.exe"
        git = "git.exe"
    elif hostOS == "Linux" or hostOS == "Darwin":
        hostOS = "linux"
        rsync = "rsync"
        git = "git"
    else:
        uprint(COLORS.RED + "Unsupported OS '" + hostOS + "'" + COLORS.DEFAULT)
        exit(1)

setOS()

def check_url_access(url):
    try:
        url = re.sub('.*@', '', urlparse(url).netloc)
        url = "http://" + url
        urlopen(url, timeout=30)
    except HTTPError:
        pass
    except Exception as e:
        return False, e
    return True, None

def gitCheckout(url, destination, clean=False):
    ret = runDisplayCommand('git clone {} {}'.format(url, destination))
    ret += gitUpdate(destination)
    if clean:
        ret += runDisplayCommand('git clean -dfx')
    return ret

def gitUpdate(path, reset=False, clean=False):
    pwd = os.getcwd()
    os.chdir(path)
    runDisplayCommand('git fetch')
    if reset:
        ret = runDisplayCommand('git reset --hard origin')
    else:
        ret = runDisplayCommand('git pull --rebase')
        ret += runDisplayCommand('git submodule update --init --recursive')
    if clean:
        ret += runDisplayCommand('git clean -dfx')
    os.chdir(pwd)
    return ret

def uprint(line):
    print(line)
    sys.stdout.flush()

def runDisplayCommand(cmd, use_check_call=False):
    uprint(COLORS.YELLOW + cmd + COLORS.DEFAULT)
    if use_check_call:
        return check_call(cmd)
    else:
        return os.system(cmd)

def svnUpdateForce(path="", revParam="", svnOptions=""):
    if path != "":
         path = " " +  path
    if revParam != "":
        revParam = " " + revParam
    if svnOptions != "":
        svnOptions = " " + svnOptions
    runDisplayCommand("svn cleanup" + path)
    svn_update_cmd = "svn update --force --accept mine-full" + revParam + svnOptions + path
    if runDisplayCommand(svn_update_cmd) != 0:
        if runDisplayCommand("svn resolve --accept mine-full -R" +  path) != 0:
            runDisplayCommand("svn resolve --accept working -R" +  path)
        return runDisplayCommand(svn_update_cmd)
    return 0

def svnCleanDirectory(svn_directory):
    unversioned_regexp = re.compile('^ ?[\?ID] *[1-9 ]*[a-zA-Z]* +(.*)')
    for cmd_line in  os.popen('svn status --no-ignore -v ' + svn_directory).readlines():
        match_result = unversioned_regexp.match(cmd_line)
        if match_result:
            to_del = match_result.group(1)
            uprint("Removing '{}'...".format(to_del))
            if os.path.isdir(to_del):
                rmtree(to_del, onerror=del_rw)
            else:
                os.remove(to_del)

def svnCheckout(url, revision, destination, cache="", reset=False, clean=False):
    """ The cache system improves performance of initial branch builds on continuous integration"""
    svnDestination = destination
    ret = 0
    useCache=False
    if cache:
        if not os.access(destination+"/"+".svn", os.R_OK):
            svnDestination = cache + "/" + re.sub("[.][.]/","/", destination)
            if not os.access(svnDestination, os.R_OK):
                os.makedirs(svnDestination)
            if not which(rsync):
                uprint(COLORS.RED + "Need rsync in the PATH to use the cache" + COLORS.DEFAULT)
                exit(1)
            useCache=True
            uprint(COLORS.BLUE + "Will use cache since this is an initial checkout" + COLORS.DEFAULT)
        else:
            useCache=False
            uprint(COLORS.BLUE + "Will not use cache, checkout has already been done" + COLORS.DEFAULT)

    # checkout to the final dest or to the cache
    if revision != "trunk":
        revParam = "-r " + revision
        revURL = "@"+revision
    else:
        revParam = ""
        revURL = ""

    svn_checkout_cmd = "svn checkout --force {0} {1}{2} {3}".format(svnoptions, url, revURL, svnDestination)
    if not os.access(destination+"/"+".svn", os.R_OK):
        ret = runDisplayCommand(svn_checkout_cmd)
    else:
        xml_str = check_output(["svn", "info", "--xml", svnDestination])
        xml_info = etree.fromstring(xml_str)
        xml_item = xml_info.find(".//url")
        current_svn_url = xml_item.text
        uprint("svn url: " + current_svn_url)
        if(current_svn_url.rstrip('/') != url.rstrip('/')):
            #SVN URL has changed, let's change the targeted svn url
            uprint("SVN URL changed from " + current_svn_url + " to " + url)
            ret = 1
            if os.path.exists(svnDestination):
                runDisplayCommand("svn cleanup " + svnDestination)
                svn_switch_cmd = "svn switch --force {0} --ignore-ancestry --accept theirs-full {1}{2} {3}".format(svnoptions, url, revURL, svnDestination)
                runDisplayCommand(svn_switch_cmd)
                ret = os.system("svn status " + svnDestination)
            if ret != 0:
                ret = svnUpdateForce(svnDestination, revParam, svnoptions)
                if ret != 0:
                    rmtree(svnDestination +"/"+".svn", onerror=del_rw)
                    ret = runDisplayCommand(svn_checkout_cmd)
                    reset = True
                    clean = True
        else:
            ret = svnUpdateForce(svnDestination, revParam, svnoptions)
    if reset:
        ret = runDisplayCommand("svn revert -R " + svnDestination)
    if clean:
        svnCleanDirectory(svnDestination)

    if ret != 0:
        uprint(COLORS.RED + "Error updating from SVN, will try using rename fallback" + COLORS.DEFAULT)
        new_dirname = svnDestination + '.bak.'+datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        try:
            os.rename(svnDestination, new_dirname)
        except:
            pass
        ret = runDisplayCommand(svn_checkout_cmd)
        if ret != 0:
            try:
                os.rename(new_dirname, svnDestination)
            except:
                pass
            uprint(COLORS.RED + "Fallback failed, stopping gism update for: " + destination + COLORS.DEFAULT)
            return 1

    if useCache:
        uprint("Copy the cache to the final destination")
        if not os.access(destination, os.R_OK):
            os.makedirs(destination)
        if hostOS == "win":
            command = rsync + " -avW --no-compress --chmod=ug=rwX \"" + \
                      re.sub(r"[\/\\ ]+","/",re.sub("([A-Za-z]):","/cygdrive/\\1",svnDestination)) + "/\" " + destination + "/"
        else:
            command = "cp -al " + svnDestination + " " + destination
        ret += runDisplayCommand(command)
    return ret

commentRE = re.compile('^#')
svnRE = re.compile('^http://')
gitRE = re.compile('^ssh://')
includeRE = re.compile('^include')


def update(cache="", modules="modules.txt", dest=".", template="modules_template.txt", buildonly=False, runtimeonly=False, recursive=False, reset=False, variables={}, svnparameters=None, clean=False):
    global svnoptions
    ret = 0

    if svnparameters:
        svnoptions += " " + svnparameters

    # test if file exist otherwise, uses template
    if (not os.access(modules, os.R_OK)):
        if (os.access(template, os.R_OK)):
            copyfile(template, modules)
        else:
            print("\n*** Error: could not open '{}'".format(modules))
            sys.exit(2)

    lines = [line.strip() for line in open(modules) if line.strip()]
    previousDir = os.getcwd()
    os.chdir(dest)

    for line in lines:
        if commentRE.match(line):
            continue
        uprint("\n## in " + os.getcwd())
        uprint("## " + "processing: " + COLORS.GREEN + line + COLORS.DEFAULT + " recursive=" + str(recursive))
        for key in variables:
            newline = line.replace("${" + key + "}", variables[key])
            if newline != line:
                uprint("replaced: ${" + key + "} by " + variables[key])
                line = newline
        platform, url, destination, revision = line.split()
        if ((hostOS in platform) or ('all' in platform)) \
                and (((not buildonly) and (not 'buildonly' in platform)) \
                    or ((buildonly ) and (not 'runtimeonly' in platform))):
            revision = revision.strip()
            doRecursion = recursive
            url_status, url_error = check_url_access(url)
            if not url_status:
                uprint(COLORS.RED + "*** Error: could not access " + url + " (" + str(url_error) + ")" + COLORS.DEFAULT)
                return 1
            if svnRE.match(url):
                    retvalue = svnCheckout(url, revision, destination, cache, reset, clean)
                    if retvalue != 0:
                        uprint(COLORS.RED + "*** Error: could not checkout " + url + COLORS.DEFAULT)
                    ret += retvalue
            elif gitRE.match(url):
                if os.access(destination+"/.git", os.R_OK):
                    ret += gitUpdate(destination, reset, clean)
                else:
                    ret += gitCheckout(url, destination, clean)
            elif includeRE.match(url):
                pass
            else:
                doRecursion = False
                uprint(COLORS.RED + "Unsupported URL scheme at the moment" + COLORS.DEFAULT)

            if(doRecursion):
                pwd = os.getcwd()
                os.chdir(destination)
                if (os.access("bootstrap.py", os.R_OK)):
                    uprint(COLORS.PINK + ">>> execute bootstrap.py in " + destination + COLORS.DEFAULT)
                    ret += runDisplayCommand("python bootstrap.py")
                    uprint(COLORS.PINK + "<<<" + COLORS.DEFAULT)
                elif (os.access(modules, os.R_OK)):
                    uprint(COLORS.PINK + ">>> execute modules.txt in " + destination + COLORS.DEFAULT)
                    ret += update(cache=cache, modules=modules, dest=".", buildonly=buildonly,
                                 runtimeonly=runtimeonly, recursive=recursive)
                    uprint(COLORS.PINK + "<<<" + COLORS.DEFAULT)
                os.chdir(pwd)
    os.chdir(previousDir)
    return ret


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('--cache', help='Specify a PATH to cache svn (for continous integration)')
    parser.add_argument('--buildonly', help='Do not checkout runtime only dependencies', action='store_true')
    parser.add_argument('--modules', default="modules.txt", help='Specify a modules file')
    parser.add_argument('--dest', default=".", help='Specify a destination PATH for the whole treem')
    parser.add_argument('--recursive', help='find modules.txt recursively and update them', action='store_true')
    parser.add_argument('--template', help='Use template file')
    parser.add_argument('--useCommitTime', help="Use the commit time for checkouted files", action='store_true')
    parser.add_argument('--nocolor', help="Do not use colored display", action='store_true')
    parser.add_argument('--reset', help="Revert modules to their initial file states", action='store_true')
    parser.add_argument('--clean', help="Remove untracked files", action='store_true')
    parser.add_argument('--variables', help="Specify variables in JSON format. They will be used in modules.txt as ${Variable}")
    parser.add_argument('--svnparameters', help="Allows to add parameters to svn checkout/update commands, for instance: --svnparameters=\"--username=...")

    args, unknown = parser.parse_known_args()

    if unknown:
        uprint("*** Error: " + os.path.basename(__file__) + " has no option: " )
        for option in unknown:
            uprint(option)
        sys.exit(1)

    if args.nocolor:
        doNotUseColors()
    template = "modules_template.txt"
    if args.template:
        template = args.template
    if args.useCommitTime:
        svnoptions += " --config-option config:miscellany:use-commit-times=yes"
    variables={}
    if args.variables:
        try:
            variables = json.loads(args.variables)
        except Exception as e:
            print("Could not parse given variables. Please use JSON format (ex.: '{\"myvar\": \"myval\"}')")
            sys.exit(2)
    sys.exit(update(cache=args.cache, buildonly=args.buildonly, template=template, modules=args.modules, dest=args.dest, recursive=args.recursive, reset=args.reset, variables=variables, svnparameters=args.svnparameters, clean=args.clean))
