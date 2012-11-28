# Copyright (c) 2012, Calxeda Inc.
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
# * Neither the name of Calxeda Inc. nor the names of its contributors
# may be used to endorse or promote products derived from this software
# without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDERS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
# OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
# TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF
# THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.


import os
import time
import traceback
import subprocess

from pkg_resources import parse_version
from pyipmi import make_bmc, IpmiError
from pyipmi.bmc import LanBMC as BMC
from tftpy.TftpShared import TftpException

from cxmanage_api import temp_file
from cxmanage_api.tftp import InternalTftp
from cxmanage_api.image import Image as IMAGE
from cxmanage_api.ubootenv import UbootEnv as UBOOTENV
from cxmanage_api.infodump import get_info_dump
from cxmanage_api.cx_exceptions import NoIpInfoError, TimeoutError, \
        NoSensorError, NoFirmwareInfoError, SocmanVersionError, \
        FirmwareConfigError, PriorityIncrementError, NoPartitionError, \
        TransferFailure, ImageSizeError, NoMacAddressError


class Node(object):
    """A node is a single instance of an ECME.

    >>> # Typical usage ...
    >>> from cxmanage_api.node import Node
    >>> node = Node(ip_adress='10.20.1.9', verbose=True)

    :param ip_address: The ip_address of the Node.
    :type ip_address: string
    :param username: The login username credential. [Default admin]
    :type username: string
    :param password: The login password credential. [Default admin]
    :type password: string
    :param tftp: The internal/external TFTP server to use for data xfer.
    :type tftp: `Tftp <tftp.html>`_
    :param verbose: Flag to turn on verbose output (cmd/response).
    :type verbose: boolean
    :param bmc: BMC object for this Node. Default: pyipmi.bmc.LanBMC
    :type bmc: BMC
    :param image: Image object for this node. Default cxmanage_api.Image
    :type image: `Image <image.html>`_
    :param ubootenv: UbootEnv  for this node. Default cxmanage_api.UbootEnv
    :type ubootenv: `UbootEnv <ubootenv.html>`_

    """

    def __init__(self, ip_address, username="admin", password="admin",
                  tftp=None, verbose=False, bmc=None, image=None,
                  ubootenv=None):
        """Default constructor for the Node class."""
        if (not tftp):
            tftp = InternalTftp()

        # Dependency Integration
        if (not bmc):
            bmc = BMC
        if (not image):
            image = IMAGE
        if (not ubootenv):
            ubootenv = UBOOTENV

        self.ip_address = ip_address
        self.username = username
        self.password = password
        self.tftp = tftp
        self.verbose = verbose

        self.bmc = make_bmc(bmc, hostname=ip_address, username=username,
                            password=password, verbose=verbose)
        self.image = image
        self.ubootenv = ubootenv

    def __eq__(self, other):
        return isinstance(other, Node) and self.ip_address == other.ip_address

    def __hash__(self):
        return hash(self.ip_address)

    @property
    def tftp_address(self):
        """Returns the tftp_address (ip:port) that this node is using.

        >>> node.tftp_address
        '10.20.2.172:35123'

        :returns: The tftp address and port that this node is using.
        :rtype: string

        """
        return '%s:%s' % (self.tftp.get_address(relative_host=self.ip_address),
                          self.tftp.port)

    def get_mac_addresses(self):
        """Gets a list of MAC addresses for this node.

        >>> node.get_macaddrs()
        ['fc:2f:40:3b:ec:40', 'fc:2f:40:3b:ec:41', 'fc:2f:40:3b:ec:42']

        :return: MAC Addresses for all interfaces.
        :rtype: list

        """
        i = 0
        result = []
        macaddr = self.bmc.get_fabric_macaddr(iface=i)
        while (macaddr):
            result.append(macaddr)
            i += 1
            macaddr = self.bmc.get_fabric_macaddr(iface=i)
        return result

    def get_power(self):
        """Returns the power status for this node.

        >>> # Powered ON system ...
        >>> node.get_power()
        True
        >>> # Powered OFF system ...
        >>> node.get_power()
        False

        :return: The power state of the Node.
        :rtype: boolean

        """
        try:
            return self.bmc.get_chassis_status().power_on
        except IpmiError as e:
            raise IpmiError(self._parse_ipmierror(e))

    def set_power(self, mode):
        """Send an IPMI power command to this target.

        >>> # To turn the power 'off'
        >>> node.set_power(mode='off')
        >>> # A quick 'get' to see if it took effect ...
        >>> node.get_power()
        False

        >>> # To turn the power 'on'
        >>> node.set_power(mode='on')

        :param mode: Mode to set the power state to. ('on'/'off')
        :type mode: string

        """
        try:
            self.bmc.set_chassis_power(mode=mode)
        except IpmiError as e:
            raise IpmiError(self._parse_ipmierror(e))

    def get_power_policy(self):
        """Return power status reported by IPMI.

        >>> node.get_power_policy()
        'always-off'

        :return: The Nodes current power policy.
        :rtype: string

        :raises IpmiError: If errors in the command occur with BMC communication.

        """
        try:
            return self.bmc.get_chassis_status().power_restore_policy
        except IpmiError as e:
            raise IpmiError(self._parse_ipmierror(e))

    def set_power_policy(self, state):
        """Set default power state for Linux side.

        >>> # Set the state to 'always-on'
        >>> node.set_power_policy(state='always-on')
        >>> # A quick check to make sure our setting took ...
        >>> node.get_power_policy()
        'always-on'

        :param state: State to set the power policy to.
        :type state: string

        """
        try:
            self.bmc.set_chassis_policy(state)
        except IpmiError as e:
            raise IpmiError(self._parse_ipmierror(e))

    def mc_reset(self):
        """Sends a Master Control reset command to the node.

        >>> node.mc_reset()

        :raises Exception: If the BMC command contains errors.
        :raises IPMIError: If there is an IPMI error communicating with the BMC.

        """
        try:
            result = self.bmc.mc_reset("cold")
            if (hasattr(result, "error")):
                raise Exception(result.error)
        except IpmiError as e:
            raise IpmiError(self._parse_ipmierror(e))

    def get_sensors(self, name=""):
        """Get a list of sensors from this target.

        .. note::
            * If no sensor name is specified, ALL sensors will be returned.

        >>> node.get_sensors()
        [<pyipmi.sdr.AnalogSdr object at 0x12d9450>,
         <pyipmi.sdr.AnalogSdr object at 0x12d9490>,
         <pyipmi.sdr.AnalogSdr object at 0x12d9510>, ... ]


        :param name: Name of the sensor you wish to get.
        :type name: string

        :return: Sensor information.
        :rtype: list

        """
        try:
            sensors = [x for x in self.bmc.sdr_list()
                        if name.lower() in x.sensor_name.lower()]
        except IpmiError as e:
            raise IpmiError(self._parse_ipmierror(e))

        if (len(sensors) == 0):
            if (name == ""):
                raise NoSensorError("No sensors were found")
            else:
                raise NoSensorError("No sensors containing \"%s\" were " +
                                    "found" % name)
        return sensors

    def get_firmware_info(self):
        """Gets firmware info from the node.

        >>> node.get_firmware_info()
        [<pyipmi.fw.FWInfo object at 0x2019850>,
        <pyipmi.fw.FWInfo object at 0x2019b10>,
        <pyipmi.fw.FWInfo object at 0x2019610>, ...]

        :return: Returns a list of FWInfo objects for each
        :rtype: list

        :raises NoFirmwareInfoError: If no fw info exists for any partition.
        :raises IpmiError: If errors in the command occur with BMC communication.

        """
        try:
            fwinfo = [x for x in self.bmc.get_firmware_info()
                      if hasattr(x, "partition")]
            if (len(fwinfo) == 0):
                raise NoFirmwareInfoError("Failed to retrieve firmware info")

            # Clean up the fwinfo results
            for entry in fwinfo:
                if (entry.version == ""):
                    entry.version = "Unknown"

            # Flag CDB as "in use" based on socman info
            for a in range(1, len(fwinfo)):
                previous = fwinfo[a - 1]
                current = fwinfo[a]
                if (current.type.split()[1][1:-1] == "CDB" and
                        current.in_use == "Unknown"):
                    if (previous.type.split()[1][1:-1] != "SOC_ELF"):
                        current.in_use = "1"
                    else:
                        current.in_use = previous.in_use
            return fwinfo
        except IpmiError as error_details:
            raise IpmiError(self._parse_ipmierror(error_details))

    def is_updatable(self, package, partition_arg="INACTIVE", priority=None):
        """Checks to see if the node can be updated with this firmware package.

        >>> from cxmanage_api.firmware_package import FirmwarePackage
        >>> fwpkg = FirmwarePackage('ECX-1000_update-v1.7.1-dirty.tar.gz')
        >>> fwpkg.version
        'ECX-1000-v1.7.1-dirty'
        >>> node.is_updatable(fwpkg)
        True

        :return: Whether the node is updatable or not.
        :rtype: boolean

        """
        try:
            self._check_firmware(package, partition_arg, priority)
            return True
        except (SocmanVersionError, FirmwareConfigError,
                PriorityIncrementError, NoPartitionError):
            return False

    def update_firmware(self, package, partition_arg="INACTIVE",
                          priority=None):
        """ Update firmware on this target.

        >>> from cxmanage_api.firmware_package import FirmwarePackage
        >>> fwpkg = FirmwarePackage('ECX-1000_update-v1.7.1-dirty.tar.gz')
        >>> fwpkg.version
        'ECX-1000-v1.7.1-dirty'
        >>> node.update_firmware(package=fwpkg)

        :param  package: Firmware package to deploy.
        :type package: `FirmwarePackage <firmware_package.html>`_
        :param partition_arg: Partition to upgrade to.
        :type partition_arg: string

        :raises PriorityIncrementError: If the SIMG Header priority cannot be
                                        changed.

        """
        fwinfo = self.get_firmware_info()

        # Get the new priority
        if (priority == None):
            priority = self._get_next_priority(fwinfo, package)

        for image in package.images:
            if (image.type == "UBOOTENV"):
                # Get partitions
                running_part = self._get_partition(fwinfo, image.type, "FIRST")
                factory_part = self._get_partition(fwinfo, image.type,
                        "SECOND")

                # Update factory ubootenv
                self._upload_image(image, factory_part, priority)

                # Update running ubootenv
                old_ubootenv_image = self._download_image(running_part)
                old_ubootenv = self.ubootenv(open(
                                        old_ubootenv_image.filename).read())
                if ("bootcmd_default" in old_ubootenv.variables):
                    ubootenv = self.ubootenv(open(image.filename).read())
                    ubootenv.variables["bootcmd_default"] = \
                                    old_ubootenv.variables["bootcmd_default"]

                    filename = temp_file()
                    with open(filename, "w") as f:
                        f.write(ubootenv.get_contents())
                    ubootenv_image = self.image(filename, image.type, False,
                                           image.daddr, image.skip_crc32,
                                           image.version)
                    self._upload_image(ubootenv_image, running_part,
                            priority)
                else:
                    self._upload_image(image, running_part, priority)

            else:
                # Get the partitions
                if (partition_arg == "BOTH"):
                    partitions = [self._get_partition(fwinfo, image.type,
                            "FIRST"), self._get_partition(fwinfo, image.type,
                            "SECOND")]
                else:
                    partitions = [self._get_partition(fwinfo, image.type,
                            partition_arg)]

                # Update the image
                for partition in partitions:
                    self._upload_image(image, partition, priority)

        if package.version:
            self.bmc.set_firmware_version(package.version)

    def config_reset(self):
        """Resets configuration to factory defaults.

        >>> node.config_reset()

        :raises IpmiError: If errors in the command occur with BMC communication.
        :raises Exception: If there are errors within the command response.

        """
        try:
            # Reset CDB
            result = self.bmc.reset_firmware()
            if (hasattr(result, "error")):
                raise Exception(result.error)

            # Reset ubootenv
            fwinfo = self.get_firmware_info()
            running_part = self._get_partition(fwinfo, "UBOOTENV", "FIRST")
            factory_part = self._get_partition(fwinfo, "UBOOTENV", "SECOND")
            image = self._download_image(factory_part)
            self._upload_image(image, running_part)
            # Clear SEL
            self.bmc.sel_clear()
        except IpmiError as e:
            raise IpmiError(self._parse_ipmierror(e))

    def set_boot_order(self, boot_args):
        """Sets boot-able device order for this node.

        >>> node.set_boot_order(boot_args=['pxe', 'disk'])

        :param boot_args: Arguments list to pass on to the uboot environment.
        :type boot_args: list

        """
        fwinfo = self.get_firmware_info()
        first_part = self._get_partition(fwinfo, "UBOOTENV", "FIRST")
        active_part = self._get_partition(fwinfo, "UBOOTENV", "ACTIVE")

        # Download active ubootenv, modify, then upload to first partition
        image = self._download_image(active_part)
        ubootenv = self.ubootenv(open(image.filename).read())
        ubootenv.set_boot_order(boot_args)
        priority = max(int(x.priority, 16) for x in [first_part, active_part])

        filename = temp_file()
        with open(filename, "w") as f:
            f.write(ubootenv.get_contents())

        ubootenv_image = self.image(filename, image.type, False, image.daddr,
                                    image.skip_crc32, image.version)
        self._upload_image(ubootenv_image, first_part, priority)

    def get_boot_order(self):
        """Returns the boot order for this node.

        >>> node.get_boot_order()
        ['pxe', 'disk']

        """
        return self.get_ubootenv().get_boot_order()

    def info_basic(self):
        """Get basic SoC info from this node.

        >>> info = node.info_basic()
        >>> info
        <pyipmi.info.InfoBasicResult object at 0x2019b90>
        >>> # Some useful information ...
        >>> info.a9boot_version
        'v2012.10.16'
        >>> info.cdb_version
        'v0.9.1'

        :returns: The results of IPMI info basic command.
        :rtype: pyipmi.info.InfoBasicResult

        :raises IpmiError: If errors in the command occur with BMC communication.
        :raises Exception: If there are errors within the command response.
        """
        result = self.bmc.get_info_basic()
        if (hasattr(result, "error")):
            raise Exception(result.error)

        result.soc_version = "v%s" % result.soc_version
        fwinfo = self.get_firmware_info()
        components = [("cdb_version", "CDB"),
                      ("stage2_version", "S2_ELF"),
                      ("bootlog_version", "BOOT_LOG"),
                      ("a9boot_version", "A9_EXEC"),
                      ("uboot_version", "A9_UBOOT"),
                      ("ubootenv_version", "UBOOTENV"),
                      ("dtb_version", "DTB")]
        for var, ptype in components:
            try:
                partition = self._get_partition(fwinfo, ptype, "ACTIVE")
                setattr(result, var, partition.version)
            except NoPartitionError:
                pass
        try:
            card = self.bmc.get_info_card()
            setattr(result, "card", "%s X%02i" %
                    (card.type, int(card.revision)))
        except IpmiError as err:
            if (self.verbose):
                print str(err)
            # Should raise a cxmanage error, but we want to allow the command
            # to continue gracefully if socman is out of date.
            setattr(result, "card", "Unknown")
        return result

    def info_dump(self):
        """Returns an info dump from this target.

        .. seealso::
            `Info Dump <infodump.html>`_

        :return: Chassis, FRU, Sensor, Firmware, CDB, Registers info and more.
        :rtype: string

        """
        return get_info_dump(self)

    def ipmitool_command(self, ipmitool_args):
        """Send a raw ipmitool command to the node.

        >>> node.ipmitool_command(['cxoem', 'info', 'basic'])
        'Calxeda SoC (0x0096CD)\\n  Firmware Version: ECX-1000-v1.7.1-dirty\\n
        SoC Version: 0.9.1\\n  Build Number: A69523DC \\n
        Timestamp (1351543656): Mon Oct 29 15:47:36 2012'

        :param ipmitool_args: Arguments to pass to the ipmitool.
        :type ipmitool_args: list

        """
        if ("IPMITOOL_PATH" in os.environ):
            command = [os.environ["IPMITOOL_PATH"]]
        else:
            command = ["ipmitool"]

        command += ["-U", self.username, "-P", self.password, "-H",
                self.ip_address]
        command += ipmitool_args

        if (self.verbose):
            print "Running %s" % " ".join(command)

        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        return (stdout + stderr).strip()

    def get_ubootenv(self):
        """Get the active u-boot environment.

        >>> node.get_ubootenv()
        <cxmanage_api.ubootenv.UbootEnv instance at 0x209da28>

        :return: U-Boot Environment object.
        :rtype: `UBootEnv <ubootenv.html>`_

        """
        fwinfo = self.get_firmware_info()
        partition = self._get_partition(fwinfo, "UBOOTENV", "ACTIVE")
        image = self._download_image(partition)
        return self.ubootenv(open(image.filename).read())

    def get_fabric_ipinfo(self):
        """Gets what ip information THIS node knows about the Fabric.

        >>> node.get_fabric_ipinfo()
        {0: '10.20.1.9', 1: '10.20.2.131', 2: '10.20.0.220', 3: '10.20.2.5'}

        :return: Returns a map of node_ids->ip_addresses.
        :rtype: dictionary

        :raises NoIpInfoError: If no results are returned.
        :raises Exception: If there are errors within the command response.
        :raises IOError: If the TFTP file to read from does not exist.

        """
        filename = temp_file()
        basename = os.path.basename(filename)
        try:
            result = self.bmc.get_fabric_ipinfo(basename, self.tftp_address)
        except IpmiError as err:
            raise IpmiError(self._parse_ipmierror(err))

        if (hasattr(result, "error")):
            raise Exception(result.error)

        # Wait for file
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                time.sleep(1)
                self.tftp.get_file(src=basename, dest=filename)
                if (os.path.getsize(filename) > 0):
                    break
            except (TftpException, IOError):
                pass

        # Parse addresses from ipinfo file
        results = {}
        for line in open(filename):
            if (line.startswith("Node")):
                elements = line.split()
                node_id = int(elements[1].rstrip(":"))
                node_ip_address = elements[2]

                # Old boards used to return 0.0.0.0 sometimes -- might not be
                # an issue anymore.
                if (node_ip_address != "0.0.0.0"):
                    results[node_id] = node_ip_address

        # Make sure we found something
        if (not results):
            raise NoIpInfoError("Node failed to reach TFTP server")
        return results

    def get_fabric_macaddrs(self):
        """Gets what macaddr information THIS node knows about the Fabric.

        :return: Returns a map of node_ids->ports->mac_addresses.
        :rtype: dictionary

        :raises NoMacAddressError: If no results are returned.
        :raises Exception: If there are errors within the command response.
        :raises IOError: If the TFTP file to read from does not exist.

        """
        filename = temp_file()
        basename = os.path.basename(filename)
        try:
            result = self.bmc.get_fabric_macaddresses(basename, self.tftp_address)
        except IpmiError as err:
            raise IpmiError(self._parse_ipmierror(err))

        if (hasattr(result, "error")):
            raise Exception(result.error)

        # Wait for file
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                time.sleep(1)
                self.tftp.get_file(src=basename, dest=filename)
                if (os.path.getsize(filename) > 0):
                    break
            except (TftpException, IOError):
                pass

        # Parse addresses from ipinfo file
        results = {}
        for line in open(filename):
            if (line.startswith("Node")):
                elements = line.split()
                node_id = int(elements[1].rstrip(","))
                port = int(elements[3].rstrip(":"))
                mac_address = elements[4]

                if not node_id in results:
                    results[node_id] = {}
                results[node_id][port] = mac_address

        # Make sure we found something
        if (not results):
            raise NoMacAddressError("Node failed to reach TFTP server")
        return results

############################### Private methods ###############################

    def _get_partition(self, fwinfo, image_type, partition_arg):
        """Get a partition for this image type based on the argument."""
        # Filter partitions for this type
        partitions = [x for x in fwinfo if
                      x.type.split()[1][1:-1] == image_type]
        if (len(partitions) < 1):
            raise NoPartitionError("No partition of type %s found on host"
                    % image_type)

        if (partition_arg == "FIRST"):
            return partitions[0]
        elif (partition_arg == "SECOND"):
            if (len(partitions) < 2):
                raise NoPartitionError("No second partition found on host")
            return partitions[1]
        elif (partition_arg == "OLDEST"):
            # Return the oldest partition
            partitions.sort(key=lambda x: x.partition, reverse=True)
            partitions.sort(key=lambda x: x.priority)
            return partitions[0]
        elif (partition_arg == "NEWEST"):
            # Return the newest partition
            partitions.sort(key=lambda x: x.partition)
            partitions.sort(key=lambda x: x.priority, reverse=True)
            return partitions[0]
        elif (partition_arg == "INACTIVE"):
            # Return the partition that's not in use (or least likely to be)
            partitions.sort(key=lambda x: x.partition, reverse=True)
            partitions.sort(key=lambda x: x.priority)
            partitions.sort(key=lambda x: int(x.flags, 16) & 2 == 0)
            partitions.sort(key=lambda x: x.in_use == "1")
            return partitions[0]
        elif (partition_arg == "ACTIVE"):
            # Return the partition that's in use (or most likely to be)
            partitions.sort(key=lambda x: x.partition)
            partitions.sort(key=lambda x: x.priority, reverse=True)
            partitions.sort(key=lambda x: int(x.flags, 16) & 2 == 1)
            partitions.sort(key=lambda x: x.in_use == "0")
            return partitions[0]
        else:
            raise ValueError("Invalid partition argument: %s" % partition_arg)

    def _upload_image(self, image, partition, priority=None):
        """Upload a single image. This includes uploading the image, performing
        the firmware update, crc32 check, and activation.
        """
        partition_id = int(partition.partition)
        if (priority == None):
            priority = int(partition.priority, 16)
        daddr = int(partition.daddr, 16)

        # Check image size
        if (image.size() > int(partition.size, 16)):
            raise ImageSizeError("%s image is too large for partition %i" %
                    image.type, partition_id)

        # Upload image to tftp server
        filename = image.upload(self.tftp, priority, daddr)
        while (True):
            try:
                # Update the firmware
                result = self.bmc.update_firmware(filename,
                                                  partition_id, image.type,
                                                  self.tftp_address)
                if (not hasattr(result, "tftp_handle_id")):
                    raise AttributeError("Failed to start firmware upload")
                self._wait_for_transfer(result.tftp_handle_id)
                # Verify crc and activate
                result = self.bmc.check_firmware(partition_id)
                if ((not hasattr(result, "crc32")) or (result.error != None)):
                    raise AttributeError("Node reported crc32 check failure")
                self.bmc.activate_firmware(partition_id)
                break
            except Exception:
                if (self.verbose):
                    traceback.format_exc()
                raise

    def _download_image(self, partition):
        """Download an image from the target."""
        # Download the image
        filename = temp_file()
        basename = os.path.basename(filename)
        partition_id = int(partition.partition)
        image_type = partition.type.split()[1][1:-1]
        while (True):
            try:
                result = self.bmc.retrieve_firmware(basename, partition_id,
                        image_type, self.tftp_address)
                if (not hasattr(result, "tftp_handle_id")):
                    raise AttributeError("Failed to start firmware download")
                self._wait_for_transfer(result.tftp_handle_id)
                break
            except Exception:
                if (self.verbose):
                    traceback.format_exc()
                raise

        self.tftp.get_file(basename, filename)
        return self.image(filename=filename, image_type=image_type,
                          daddr=int(partition.daddr, 16),
                          version=partition.version)

    def _wait_for_transfer(self, handle):
        """Wait for a firmware transfer to finish."""
        deadline = time.time() + 180
        result = self.bmc.get_firmware_status(handle)
        if (not hasattr(result, "status")):
            raise AttributeError('Failed to retrieve firmware transfer status')

        while (result.status == "In progress"):
            if (time.time() >= deadline):
                raise TimeoutError("Transfer timed out after 3 minutes")
            time.sleep(1)
            result = self.bmc.get_firmware_status(handle)
            if (not hasattr(result, "status")):
                raise AttributeError("Failed to retrieve firmware transfer status")

        if (result.status != "Complete"):
            raise TransferFailure("Node reported TFTP transfer failure")

    def _check_firmware(self, package, partition_arg="INACTIVE", priority=None):
        """Check if this host is ready for an update."""
        info = self.info_basic()
        fwinfo = self.get_firmware_info()
        # Check socman version
        if (package.required_socman_version):
            soc_version = info.soc_version.lstrip("v")
            required_version = package.required_socman_version.lstrip("v")
            if ((package.required_socman_version and
                 parse_version(soc_version)) <
                 parse_version(required_version)):
                raise SocmanVersionError(
                        "Update requires socman version %s (found %s)"
                        % (required_version, soc_version))

        # Check firmware config
        if ((info.version != "Unknown") and (len(info.version) < 32)):
            if ((package.config == "default") and ("slot2" in info.version)):
                raise FirmwareConfigError(
                "Refusing to upload a \'default\' package to a \'slot2\' host")
            if ((package.config == "slot2") and (not "slot2" in info.version)):
                raise FirmwareConfigError(
                "Refusing to upload a \'slot2\' package to a \'default\' host")

        # Check that the priority can be bumped
        if (priority == None):
            priority = self._get_next_priority(fwinfo, package)

        # Check partitions
        for image in package.images:
            if ((image.type == "UBOOTENV") or (partition_arg == "BOTH")):
                self._get_partition(fwinfo, image.type, "FIRST")
                self._get_partition(fwinfo, image.type, "SECOND")
            else:
                self._get_partition(fwinfo, image.type, partition_arg)
        return True

    def _get_next_priority(self, fwinfo, package):
        """ Get the next priority """
        priority = None
        image_types = [x.type for x in package.images]
        for partition in fwinfo:
            partition_active = int(partition.flags, 16) & 2
            partition_type = partition.type.split()[1].strip("()")
            if ((not partition_active) and (partition_type in image_types)):
                priority = max(priority, int(partition.priority, 16) + 1)
        if (priority > 0xFFFF):
            raise PriorityIncrementError(
                            "Unable to increment SIMG priority, too high")
        return priority

    def _parse_ipmierror(self, error_details):
        """Parse a meaningful message from an IpmiError """
        try:
            error = str(error_details).lstrip().splitlines()[0].rstrip()
            if (error.startswith('Error: ')):
                error = error[7:]
            return 'IPMItool ERROR: %s' % error
        except IndexError:
            return 'IPMITool encountered an error.'


# End of file: ./node.py
