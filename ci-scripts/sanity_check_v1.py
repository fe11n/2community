#!/usr/bin/python3
"""
This is a sanity checking tool for openEuler community database
"""
import os.path
import sys
import argparse
import subprocess
import yaml

SUPPORTED_VER_MIN = 1.0
SUPPORTED_VER_MAX = 2.0

SIGS_YAML = "sig/sigs.yaml"
EXP_YAML = "zh/technical-committee/governance/exceptions.yaml"
BLC_YAML = "zh/technical-committee/governance/blacklist-software.yaml"
OE_YAML = "repository/openeuler.yaml"
M_OE_YAML = "repository/openeuler.master.yaml"
SRC_OE_YAML = "repository/src-openeuler.yaml"
M_SRC_OE_YAML = "repository/src-openeuler.master.yaml"

def check_0(community):
    """
    Validate basic versioning and setting
    """
    print("Validate basic versioning and setting of openeuler and src-openeuler")

    oe_yaml = load_yaml(community, OE_YAML)
    oe_repos = oe_yaml["repositories"]

    src_oe_yaml = load_yaml(community, SRC_OE_YAML)
    src_oe_repos = src_oe_yaml["repositories"]

    oe_version = float(oe_yaml.get("format_version", "1.0"))
    if oe_yaml["community"] != "openeuler":
        print("openeuler.yaml has wrong community setting")
        sys.exit(1)

    src_oe_version = float(src_oe_yaml.get("format_version", "1.0"))

    if src_oe_yaml["community"] != "src-openeuler":
        print("src-openeuler.yaml has wrong community setting")
        sys.exit(1)

    if oe_version != src_oe_version:
        print("Openeuler and src-openeuler have different format_version")
        sys.exit(1)

    if oe_version > SUPPORTED_VER_MAX or oe_version < SUPPORTED_VER_MIN:
        print("Current format version is out of support")
        sys.exit(1)

    return oe_repos, src_oe_repos, oe_version

def check_1(sigs, exps):
    """
    Repository in src-openeuler and openeuler should be managed by the single SIG.
    """
    print("Repository in src-openeuler and openeuler should be managed by the single SIG.")

    repositories = {}
    errors_found = 0

    for sig in sigs:
        if sig["name"] == "Private":
            continue
        for repo in sig["repositories"]:
            repo_name = repo.replace("src-openeuler/", "").replace("openeuler/", "").lower()
            supervisor = repositories.get(repo_name, set())
            supervisor.add(sig["name"])
            repositories[repo_name] = supervisor

    for repo in repositories:
        sigs = repositories[repo]
        if len(sigs) != 1:
            if repo in exps:
                continue
            print("ERROR! " + repo + ": Co-managed by these SIGs " + str(sigs))
            errors_found += 1

    if errors_found == 0:
        print("PASS WITHOUT ISSUES FOUND.")
    return errors_found


def check_2(sigs, exps):
    """
    Repository in src-openeuler or openeuler should never be duplicated.
    """
    print("Repository in src-openeuler or openeuler should never be duplicated.")

    repositories = {}
    errors_found = 0

    for sig in sigs:
        if sig["name"] == "Private":
            continue
        for repo in sig["repositories"]:
            # Gitee requires case-insenstive for repo creation
            repo = repo.lower()
            supervisor = repositories.get(repo, set())
            if sig["name"] in supervisor:
                print("ERROR! {repo} has been managed by {sig} multiple times"
                      .format(repo=repo, sig=sig["name"]))
                errors_found += 1
            else:
                supervisor.add(sig["name"])
            repositories[repo] = supervisor

    for repo in repositories:
        sigs = repositories[repo]
        if len(sigs) != 1:
            if repo in exps:
                continue
            print(repo + ": " + str(sigs) + "")
            errors_found = errors_found + 1

    if errors_found == 0:
        print("PASS WITHOUT ISSUES FOUND.")
    return errors_found


def check_3(sigs):
    """
    Repository managed by both SIG and Private.
    """
    print("Repository managed by both SIG and Private.")

    supervisors = {}

    for sig in sigs:
        for repo in sig["repositories"]:
            # Gitee requries strict case senstive naming for direct access
            # repo = repo.lower()
            supervisor = supervisors.get(repo, set())
            supervisor.add(sig["name"])
            supervisors[repo] = supervisor

    print("There're " + str(len(supervisors)) + " repositories in total.")

    co_managed = 0
    private_only = 0

    for repo in supervisors:
        sigs = supervisors[repo]
        if "Private" in sigs:
            if len(sigs) != 1:
                co_managed += 1
            else:
                private_only += 1
    print("There're " + str(co_managed) + " repositories co-managed by Private")
    print("There're " + str(private_only) + " repositories managed by Private only")
    return supervisors


def check_4(exps, prefix, oe_repos, supervisors, cross_checked_repo):
    """
    YAML in repository/ should be consisitent with sigs.yaml
    """
    print("repository/{prefix}.yaml should be consisitent with sigs.yaml".format(prefix=prefix))

    errors_found = 0

    err_msg1 = "ERROR! Repository {name} marked as public in {prefix}.yaml, "\
               "but listed in Private SIG."
    err_msg2 = "WARNING! Repository {name} marked as private in {prefix}.yaml, "\
               "but not listed in Private SIG."

    for repo in oe_repos:
        # Gitee requires strict case sensitive for direct accessing
        name = prefix + "/" + repo["name"]
        if "type" not in repo.keys():
            print("ERROR! Repository {name} has no type tag".format(name=name))
            errors_found += 1
            continue

        if name in cross_checked_repo:
            print("ERROR! Repository {name} in {prefix}.yaml has duplication."
                  .format(name=name, prefix=prefix))
            errors_found += 1
        if not supervisors.get(name, False):
            if name not in exps:
                print("ERROR! Repository {name} in {prefix}.yaml cannot be found in sigs.yaml."
                      .format(name=name, prefix=prefix))
                errors_found += 1
        if repo["type"] == "public" and "Private" in supervisors.get(name, set()):
            print(err_msg1.format(name=name, prefix=prefix))
            errors_found += 1

        if repo["type"] == "private" and "Private" not in supervisors.get(name, set()):
            print(err_msg2.format(name=name, prefix=prefix))

        cross_checked_repo.add(name)

    if errors_found == 0:
        print("PASS WITHOUT ISSUES FOUND.")
    return errors_found, cross_checked_repo


def check_6(cross_checked_repo, supervisors):
    """
    All repositories in sigs.yaml must list in either openeuler.yaml or src-openeuler.yaml
    """
    print("All repositories in sigs.yaml must list in either openeuler.yaml or src-openeuler.yaml")
    errors_found = 0

    # if len(cross_checked_repo) != len(supervisors):

    for repo in supervisors:
        if not repo in cross_checked_repo:
            print("ERROR! {name} listed in sigs.yaml, but not in {oe}.yaml"
                  .format(name=repo, oe=repo.split("/")[0]))
            errors_found = errors_found + 1

    if errors_found == 0:
        print("PASS WITHOUT ISSUES FOUND.")

    return errors_found


def check_7(oe_repos, srcoe_repos):
    """
    All repositories' name must follow the gitee requirements
    """
    print("All repositories' name must follow the gitee requirements")

    errors_found = 0
    error_msg = "Repo name allows only letters, numbers, or an underscore (_), dash (-),"\
                " and period (.). It must start with a letter, and its length is 2 to 200"\
                " characters."

    for repos in oe_repos, srcoe_repos:
        for repo in repos:
            repo_name = repo["name"].lower()
            if len(repo_name) < 2 or len(repo_name) > 200:
                print("ERROR! {name} too long or too short".format(name=repo_name))
                errors_found += 1
            else:
                new_repo_name = repo_name.replace("_", "").replace("-", "").replace(".", "")
                if not new_repo_name.isalnum():
                    print("ERROR! {name} contains invalid character".format(name=repo_name))
                    errors_found += 1
                elif not repo_name[0].isalpha():
                    print("ERROR! {name} must start with a letter".format(name=repo_name))
                    errors_found += 1

    if errors_found != 0:
        print(error_msg)
    else:
        print("PASS WITHOUT ISSUES FOUND.")

    return errors_found


# This check is inspired by PR !934
def check_8_v1(oe_repos, srcoe_repos):
    """
    All repositories' must have protected_branches
    """
    print("All repositories' must have protected_branches")

    errors_found = 0

    for repos, prefix in [(oe_repos, "openeuler/"), (srcoe_repos, "src-openeuler/")]:
        for repo in repos:
            branches = repo.get("protected_branches", [])
            if not branches:
                print("ERROR! {pre}{name} doesn\'t have protected_branches"
                      .format(pre=prefix, name=repo["name"]))
                errors_found += 1
            elif "master" not in branches:
                print("ERROR! master branch in {pre}{name} is not protected"
                      .format(pre=prefix, name=repo["name"]))
                errors_found += 1

    if errors_found == 0:
        print("PASS WITHOUT ISSUES FOUND.")

    return errors_found

def check_8_v2(oe_repos, srcoe_repos):
    """
    All repositories' must have proper branches setting
    """
    print("All repositories' must have proper branches setting")

    errors_found = 0

    for repos, prefix in [(oe_repos, "openeuler/"), (srcoe_repos, "src-openeuler/")]:
        for repo in repos:
            branches = repo.get("branches", [])
            if not branches:
                print("ERROR! {pre}{name} doesn\'t have branches"
                      .format(pre=prefix, name=repo["name"]))
                errors_found += 1
            else:
                master_found = 0
                for branch in branches:
                    if branch["type"] != "protected" and branch["type"] != "readonly":
                        print("ERROR! {pre}{name} branch {br} is not valid"
                              .format(pre=prefix, name=repo["name"], br=branch["name"]))
                        errors_found += 1
                    if branch["name"] == "master":
                        master_found  += 1
                    elif branch.get("create_from", "") == "":
                        print("ERROR! {pre}{name} branch {br} has not valid parent branch"
                              .format(pre=prefix, name=repo["name"], br=branch["name"]))
                        errors_found += 1
                else:
                    if master_found != 1:
                        print("ERROR! {pre}{name}'s master branch is not properly set"
                              .format(pre=prefix, name=repo["name"]))
                        errors_found += 1

    if errors_found == 0:
        print("PASS WITHOUT ISSUES FOUND.")

    return errors_found


def oe_requirements(repo, blacklist):
    """
    Helper to check if entry in openeuler follow openEuler requirements
    """
    errors = 0
    if len(repo.get("description", "")) < 10:
        print("ERROR! openeuler/" + repo["name"] + "\'s description is too short.")
        errors += 1
    if repo["name"] in blacklist:
        print("ERROR! openeuler/" + repo["name"] + " was black-listed.")
        print("         Because: " + blacklist[repo["name"]])
        errors += 1
    return errors


def srcoe_requirements(repo, blacklist):
    """
    Helper to check if entry in src-openeuler follow openEuler requirements
    """
    errors = 0
    if repo.get("upstream", "") == "":
        print("ERROR! src-openeuler/" + repo["name"] + " missed upstream information.")
        errors += 1
    if len(repo.get("description", "")) < 10:
        print("ERROR! src-openeuler/" + repo["name"] + "\'s description is too short.")
        errors += 1
    if repo["name"] in blacklist:
        print("ERROR! src-openeuler/" + repo["name"] + " was black-listed.")
        print("         Because: " + blacklist[repo["name"]])
        errors += 1
    return errors


def check_changed_repo(repos, prefix, super_visor, requires, blacklist):
    """
    Helper to compare current yaml and previous yaml
    """
    errors_found = 0

    curr_dict = {f["name"]: f for f in repos[0]}
    remove_repos = set()
    sigs_attention = set()

    for repo in repos[1]:
        if repo["name"] in curr_dict:
            if repo["type"] == "private" and curr_dict[repo["name"]]["type"] == "public":
                continue
            else:
                curr_dict.pop(repo["name"])
        else:
            remove_repos.add(repo["name"])

    for name in curr_dict:
        curr_repo = curr_dict[name]
        sigs = super_visor.get(prefix + curr_repo["name"], set())
        print("INFO: adding " + curr_repo["name"] + " to SIG " + str(sigs))
        sigs_attention = sigs_attention | sigs

        errors_found += requires(curr_repo, blacklist)
        if curr_repo.get("rename_from", "") in remove_repos:
            remove_repos.remove(curr_repo.get("rename_from"))

    for rm_name in remove_repos:
        sigs = super_visor.get(prefix + rm_name.lower(), set())
        sigs_attention = sigs_attention | sigs
        print("WARNING! deleting " + prefix + "%s." % rm_name)

    return errors_found, sigs_attention


def check_100(oe_repos, srcoe_repos, super_visor, community_dir):
    """
    Newly changed repositories must follow the OE requirements
    """
    print("Newly changed repositories must follow the OE requirements")
    errors_found = 0
    error_msg = """Some newly changed repositories doesn't follow the OE requirments"""

    black_list = load_yaml(community_dir, BLC_YAML)["blacklist-software"]
    black_dict = {i["name"]: i["reason"] for i in black_list}
    sigs_attention = set()

    err, sigs = check_changed_repo(oe_repos, "openeuler/",
                                   super_visor, oe_requirements, black_dict)
    errors_found += err
    sigs_attention |= sigs

    err, sigs = check_changed_repo(srcoe_repos, "src-openeuler/",
                                   super_visor, srcoe_requirements, black_dict)
    errors_found += err
    sigs_attention |= sigs

    if errors_found != 0:
        print(error_msg)
    else:
        print("PASS WITHOUT ISSUES FOUND.")

    # We are not forcing this rule yet
    if sigs_attention:
        print("\nSUGGESTION: This PR needs to be reviewed by maintainers from following SIG(s).")
        for sig in sigs_attention:
            if sig == "Private":
                continue
            else:
                print(sig, end=': ')
                owners = load_yaml(community_dir, "sig/" + sig + "/OWNERS")["maintainers"]
                for owner in owners:
                    print("@" + owner, end=' ')
                print("")

    return errors_found


def prepare_master_branch_yaml(community_dir):
    """
    Helper for preparing previous openeuler.yaml and src-openeuler.yaml
    """
    old_dir = os.getcwd()
    os.chdir(community_dir)
    git_srcoe_cmd = "git show remotes/origin/master:" + SRC_OE_YAML + " > " + M_SRC_OE_YAML
    subprocess.check_output(git_srcoe_cmd, shell=True)
    git_oe_cmd = "git show remotes/origin/master:" + OE_YAML + " > " + M_OE_YAML
    subprocess.check_output(git_oe_cmd, shell=True)
    os.chdir(old_dir)


def cleanup_master_branch_yaml(community_dir):
    """
    Helper for cleaning up previous openeuler.yaml and src-openeuler.yaml
    """
    old_dir = os.getcwd()
    os.chdir(community_dir)
    os.remove(M_SRC_OE_YAML)
    os.remove(M_OE_YAML)
    os.chdir(old_dir)


def load_yaml(directory, yaml_file):
    """
    Helper for load YAML database
    """
    yaml_path = os.path.expanduser(os.path.join(directory, yaml_file))
    try:
        result = yaml.load(open(yaml_path, encoding="utf-8"), Loader=yaml.Loader)
    except FileNotFoundError:
        print("Cannot Load %s."%(yaml_path))
        print("Could be wrong path")
        sys.exit(1)
    except yaml.scanner.ScannerError as error:
        print("%s: Invalid YAML file"%(yaml_path))
        print("Detailed Error Information:")
        print(error)
        sys.exit(1)
    return result


def main():
    """
    Main entrance of functionality
    """
    par = argparse.ArgumentParser()

    par.add_argument("community", type=str, help="Local path of community repository")
    args = par.parse_args()

    sig_list = load_yaml(args.community, SIGS_YAML)["sigs"]
    #sig_yaml = load_yaml(args.community, SIGS_YAML)["sigs"]
    #sig_list = sig_yaml["sigs"]

    exception_list = load_yaml(args.community, EXP_YAML)["exceptions"]

    repo_supervisors = {}
    repo_cross_checked = set()

    print("Sanity Check among different YAML database inside openEuler community.")
    issues_found = 0

    print("\nCheck 0:")
    oe_repos, src_oe_repos, oe_ver = check_0(args.community)

    print("\nCheck 1:")
    issues_found += check_1(sig_list, exception_list)

    print("\nCheck 2:")
    issues_found += check_2(sig_list, exception_list)

    print("\nCheck 3:")
    repo_supervisors = check_3(sig_list)

    print("\nCheck 4:")
    issues, repo_cross_checked = check_4(exception_list, "openeuler",
                                         oe_repos, repo_supervisors, repo_cross_checked)
    issues_found += issues

    print("\nCheck 5:")
    issues, repo_cross_checked = check_4(exception_list, "src-openeuler",
                                         src_oe_repos, repo_supervisors, repo_cross_checked)
    issues_found += issues

    print("\nCheck 6:")
    issues_found += check_6(repo_cross_checked, repo_supervisors)

    print("\nCheck 7:")
    issues_found += check_7(oe_repos, src_oe_repos)

    print("\nCheck 8:")
    if oe_ver < 2.0:
        issues_found += check_8_v1(oe_repos, src_oe_repos)
    else:
        issues_found += check_8_v2(oe_repos, src_oe_repos)

    print("\nCheck Last:")
    prepare_master_branch_yaml(args.community)

    prev_oe_yaml = load_yaml(args.community, M_OE_YAML)
    prev_oe_repos = prev_oe_yaml["repositories"]

    prev_src_oe_yaml = load_yaml(args.community, M_SRC_OE_YAML)
    prev_src_oe_repos = prev_src_oe_yaml["repositories"]

    issues_found += check_100([oe_repos, prev_oe_repos],
                              [src_oe_repos, prev_src_oe_repos],
                              repo_supervisors, args.community)
    cleanup_master_branch_yaml(args.community)

    sys.exit(issues_found)

if __name__ == "__main__":
    main()
