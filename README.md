# ToolTamer

**ToolTamer** is a Bash script designed to automate the installation, synchronization, and cleanup of tools and configuration files across multiple systems. It leverages existing package managers like **apt** on Linux and **Homebrew** on macOS to manage software packages, ensuring a consistent and clean working environment on all your devices.

## Features

- **Automated Package Management**: Installs missing tools and removes those not listed in your configuration, preventing system clutter.
- **Configuration Synchronization**: Manages dotfiles and configuration files, synchronizing them across systems based on checksum comparisons.
- **Cross-Platform Support**: Works seamlessly on both Linux and macOS systems.
- **Modular Configurations**: Uses a central configuration repository that can be shared and updated across systems.
- **Easy Setup**: If no configuration is present, ToolTamer prompts for a Git repository to check out the configuration.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
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
Easiest to add it to your path 😉 

## Usage

### First Run

1. **Start ToolTamer**:

   ```bash
   ./bin/tt
   ```
2. you will be asked for a git url - if you don't want to provide any, just hit enter. You will then be asked to create a default structure in `$HOME/.config/toolTamer`. If you provided an url, it will be checked out in `$HOME/.config/toolTamer`
3. then a menu will appear (if `fzf` is available, this is being used. `select` otherwise). Here you can choose either to apply the config to your system, or take a snapshot from the system and put it in your config


