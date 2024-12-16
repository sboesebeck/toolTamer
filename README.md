# ToolTamer

If you are working on several differnt machines and want to synchronize your home environment, you end up with a ton of problems: Just having all your dotfiles in a git repo usually does not work, in all cases, and it does not cover installations of tools.

There are solutions out there, that did not work for my usecases:

- Nix/Homemanager: In addition to being really slow compared to other solutions, this is really hard to maintain, and some things just do not work. Especially when combined with NixDarwin it is heavily integrated into the system and is more or less broken after each macos update. It works better on linux though in my experience
- Solutions that deal with config files alone just do not cut it imho as they do not install missing tools or reference tools in config files like bashrc that are not installed and then cause errors.

After several tries with other tools, I created my own version of a config / installation synchronization tool that maybe interesting for others:

**ToolTamer** is a Bash script designed to automate the installation, synchronization, and cleanup of tools and configuration files across multiple systems. It leverages existing package managers like **apt** on Linux and **Homebrew** on macOS to manage software packages, ensuring a consistent and clean working environment on all your devices.

## Features

- **Automated Package Management**: Installs missing tools and removes those not listed in your configuration, preventing system clutter.
- **Configuration Synchronization**: Manages dotfiles and configuration files, synchronizing them across systems based on checksum comparisons.
- **Cross-Platform Support**: Works seamlessly on both Linux and macOS systems. (not heavily tested yet) 
- **Modular Configurations**: it is designed to use git to store your configurations and make them available on all systems 
- **Easy Setup**: If no configuration is present, ToolTamer prompts for a Git repository to check out the configuration.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
  - [Configuration Repository](#configuration-repository)
  - [Directory Structure](#directory-structure)
  - [Configuration Files](#configuration-files)
- [Usage](#usage)
  - [First Run](#first-run)
  - [Menu Options](#menu-options)
- [Tips and Tricks](#tips-and-tricks)
- [Contributing](#contributing)
- [License](#license)

## Prerequisites

- **Operating System**: Linux or macOS
- **Package Manager**:
  - **Linux**: `apt` (Advanced Package Tool)
    - Install `apt-rdepends`:
      ```bash
      sudo apt install apt-rdepends
      ```
  - Arch-Linux: ToolTamer does have `pacman` support, but it was not tested yet
  - **macOS**: [Homebrew](https://brew.sh/)
    - Install Homebrew:
      ```bash
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      ```
- **Git**: Ensure Git is installed to clone repositories and manage configurations.

## Installation

1. **Clone the ToolTamer Repository**:

   ```bash
   git clone https://github.com/yourusername/tooltamer.git
   ```
2. Navigate there 
```
cd tooltamer
```
3. start the script 
```
./bin/tt
```
Easiest to add it to your path 😉 - add this line to your `.zshrc` or `.bashrc`:

```
eval "$(~/toolTamer/bin/tt -sh)"
``` 


## Usage

### First Run

1. **Start ToolTamer**:

   ```bash
   ./bin/tt
   ```
2. you will be asked for a git url - if you don't want to provide any, just hit enter. You will then be asked to create a default structure in `$HOME/.config/toolTamer`. If you provided an url, it will be checked out in `$HOME/.config/toolTamer`
3. then a menu will appear. Here you can choose either to apply the config to your system, or take a snapshot from the system and put it in your config

### Menu Options 

when running tt you will be presented with several choices. First question usually is, whether or not to update the config directory using git (it tries to run `git pull` then). You can answer either y/n...

after that you will be presented with the following options:
(all those menus usually highlight an option with a color, so you can also press this key).
```
-----> ToolTamer V1.0 - main menu
1. Update System - full system update, local files, installation, local install script
2. Files only - update only files
3. Snapshot System
4. Admin
5. Quit
Choose option -> 
```

1. will run tooltamer and compare your system with the config for this host. If no config is available, you will be asked what to do 
2. Files only will only look for changes in config files (or better: files configured in tooltamer), do not look at installed tools
3. Snapshot System: take your current configuration and put it in tooltamer. That takes all installed tools and the current version of all configured files - if no files are configured, no config is passed into tooltamer
4. Admin submenu
5. Quit (self explaining, i quess)

When opening the Admin submenu, you will get the following options:
```
----> ToolTamer V1.0 <----
---> ToolTamer Admin Menu <---
1. Move local file to ToolTamer
2. Move files between configs in ToolTamer
3. View differences of files
4. View differences of installed tools
5. Show Config
6. Fix duplicate packages
7. Git view
8. return
```

1. move an existing file from your local homedir to tooltamer (move means, take the version to tooltamer)
2. move files between config, useful, if you want to move some configuration file to common for example
3. view differences of files, shows a diff (if you want) for every configured file in tooltamer. You can then decide, what to do with that change: add the change to tooltamer, ignore it, replace the change with the version of toolTamer  
4. differences of installed tools shows, what tools should be installed, or will be deleted. You can decide, what to do here 
5. show config for your host (or any host) - not 100% implemented yet
6. fixed duplicate packages that comes with including configs. Removes those packages that are already included from your machines config 
7. opens lazygit in the tooltamers config directory 
8. returns to the main menu


## Configuration 

The Configuration of ToolTamer is located in `$HOME/.config/toolTamer` and relies on hostname of your machine.

ToolTamer looks for a directory in it`s config directory named as the hostname from that machine (can also be a symbolic link). There should be several files: 

- `to_install.brew` or `to_install.apt` or `to_install.pacman`: List of packages for the machine to be installed, depending on package manager. 
- `includes.conf`: ToolTamer supports an easy hierachy, you can define hostnames / directories to include into your config. 
- `local_install.sh`: This script will be run _every time_ tt is run on that machine.
- `files.conf`: configuration file telling tt where to put the files found in the `files` subdirectory.

There is one special directory called `common`. This contains files / configurations that are included by all other configurations.
in common there might be all files listed above, or just one of them. Depending on your setup 

so, a directory structure might look something like this:

```
.config/toolTamer/configs 
    -> common/
       -> to_install.apt  
       -> to_install.brew
       -> files.conf 
       -> files/
          -> bashrc
          -> kitty.conf
    -> common_mac/
       -> to_install.brew
       -> local_install.sh
       -> files.conf 
       -> files/
          -> aerospace.conf
    -> myMacBook1/
       -> includes.conf
       -> to_install.brew
       -> local_install.sh
       -> files.conf 
       -> files/
          -> aerospace.conf
```  

In that example the includes.conf file of `myMacBook1` contains the line `common_mac` to include the basic mac configuration.

if files exist both in included and in local config, the local config wins. Or better: when running through all includes, toolTamer tries to take the latest one. Meaning: If a file is included in common, but also in some config included, the included config wins.
If a file is configured in some included config and in your host configuration, the host configuration wins.

The `local_install.sh` scripts are executed in order: common first, then the includes (in order) then the file for the current host.

### includes.conf
A simple file just containing a list of other configurations to include.
This is not recursive! So an included configs includes.conf is not processed in addition to that one!

### files.conf
To deal with local config files or files in general, the files are stored in the `files` directory, but to know where to copy it to and what to compare it with, the files.conf is used. Very simple format:

```
filename:target relative to your $HOME 
```  

For example:
```
myzshrc:.zshrc
shellScript1:bin/
shellScript2:bin/
```

In this case, the file `$HOME/.config/toolTamer/configs/HOSTNAME/files/myzshrc` will be compared with your `.zshrc` in your home directory. The two scripts are both compared with files with the same name in `$HOME/bin`.

Comparison is done using `SHA` Checksums!


### to_insall.XXX
The `to_install` files just contain a list of package names to be ensured on the system. Everything that is installed on the system, that is not a dependency or a lib that is not in that list, will be uninstalled / purged. This way, whenever you try out a tool and forget to uninstall it, ToolTamer will help you with that.

