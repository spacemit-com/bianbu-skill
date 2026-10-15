# Installing CoreMark

CoreMark is installed from the distribution package. This guide does not build it from source, and does not treat a missing package as a reason to build one.

Check what is present before proposing anything, and get the user's consent before installing packages or writing to the system.

## Check the platform and what is already there

```bash
uname -m                                  # expect riscv64
command -v coremark                       # already installed?
cat /etc/os-release                       # distribution and release
```

If `coremark` is already installed, stop here and go to [running](run.md).

## Refresh the index, then check availability

`apt-cache policy` reads the local package index, so refresh it first. An index that has never been updated can make an available package look missing, and that mistake would send the user hunting for a build they do not need.

```bash
sudo apt update
apt-cache policy coremark
```

The output tells you which case you are in:

| Output | Meaning |
| --- | --- |
| A `Candidate:` line naming a version | The configured archive carries the package; install it |
| `Candidate: (none)` | The package is not in the configured archive; report the gap and stop |

## Install and verify

```bash
sudo apt install coremark
command -v coremark        # expect /usr/bin/coremark
coremark --help            # the packaged command supports -h and -q
```

The package installs `/usr/bin/coremark`, a wrapper around `/usr/libexec/coremark/coremark`. The wrapper saves every run to a log file and prints its path on standard error; see [reporting](report.md). It needs no build tools, so no compiler, `make` or `git` has to be installed.

## When no candidate is available

The package is not in the configured archive. Report that to the user plainly, quoting the `apt-cache policy` output as evidence, and stop there:

- Do not add a third-party repository, PPA or download URL.
- Do not substitute a build from source.
- Do not retry the same command hoping for a different result.

State which archive was consulted and what the user can do next — check the system's configured repositories, or raise it with their distribution's maintainers — and let them decide. A missing package is a fact to report, not a problem for this guide to work around.

## Requirements

| Need | Why |
| --- | --- |
| `sudo` | Installing a package |
| Network access | Reaching the configured archive |
| A supported platform | riscv64 Bianbu, or a compatible riscv64 Linux distribution |
