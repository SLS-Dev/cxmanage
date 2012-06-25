#Copyright 2012 Calxeda, Inc.  All rights reserved.

""" Target objects used by the cxmanage controller """

import os
import socket
import subprocess
import sys
import time

from cxmanage import CxmanageError

from pyipmi import make_bmc, IpmiError
from pyipmi.bmc import LanBMC

class Target:
    """ Contains info for a single target. A target consists of a hostname,
    an username, and a password. """

    def __init__(self, address, username="admin",
            password="admin", verbosity=1):
        self.address = address
        self.username = username
        self.password = password
        self.verbosity = verbosity

        verbose = verbosity >= 2
        self.bmc = make_bmc(LanBMC, hostname=address,
                username=username, password=password, verbose=verbose)

    def get_fabric_ipinfo(self, tftp, filename):
        """ Download IP info from this target """
        tftp_address = "%s:%s" % (tftp.get_address(self.address),
                tftp.get_port())
        basename = os.path.basename(filename)

        # Send ipinfo command
        try:
            self.bmc.get_fabric_ipinfo(basename, tftp_address)
        except IpmiError:
            raise CxmanageError("Failed to retrieve IP info")

        # Wait for file
        for a in range(10):
            try:
                time.sleep(1)
                tftp.get_file(basename, filename)
                if os.path.getsize(filename) > 0:
                    break
            except CxmanageError:
                pass

        # Ensure file is present and not empty
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            raise CxmanageError("Failed to retrieve IP info")

    def power(self, mode):
        """ Send an IPMI power command to this target """
        try:
            self.bmc.set_chassis_power(mode=mode)
        except IpmiError:
            raise CxmanageError("Failed to send power %s command" % mode)

    def power_policy(self, state):
        """ Set default power state for A9 """
        try:
            self.bmc.set_chassis_policy(state)
        except IpmiError:
            raise CxmanageError("Failed to set power policy to \"%s\"" % state)

    def power_policy_status(self):
        """ Return power status reported by IPMI """
        try:
            return self.bmc.get_chassis_status().power_restore_policy
        except IpmiError:
            raise CxmanageError("Failed to retrieve power status")

    def power_status(self):
        """ Return power status reported by IPMI """
        try:
            if self.bmc.get_chassis_status().power_on:
                return "on"
            else:
                return "off"
        except IpmiError:
            raise CxmanageError("Failed to retrieve power status")

    def mc_reset(self):
        """ Send an IPMI MC reset command to the target """
        try:
            result = self.bmc.mc_reset("cold")
            if hasattr(result, "error"):
                raise CxmanageError("Failed to send MC reset command")
        except IpmiError:
            raise CxmanageError("Failed to send MC reset command")

    def update_firmware(self, work_dir, tftp, images, slot_arg):
        """ Update firmware on this target. """
        # Get all updates
        self._vwrite(1, "Updating %s" % self.address)

        try:
            plan = self._get_update_plan(images, slot_arg)
            for image, slot, new_version in plan:
                self._update_image(work_dir, tftp, image, slot, new_version)
        finally:
            self._vwrite(1, "\n")

    def get_sensor(self, name):
        """ Read a sensor value from this target """
        try:
            sensors = [x for x in self.bmc.sdr_list() if x.sensor_name == name]
            if len(sensors) < 1:
                raise CxmanageError("Sensor \"%s\" not found" % name)
            return sensors[0].sensor_reading
        except IpmiError:
            raise CxmanageError("Failed to retrieve sensor value")

    def config_reset(self):
        """ Reset configuration to factory default """
        try:
            # Reset CDB
            result = self.bmc.reset_firmware()
            if hasattr(result, "error"):
                raise CxmanageError("Failed to reset configuration")

            # Clear SEL
            self.bmc.sel_clear()

        except IpmiError:
            raise CxmanageError("Failed to reset configuration")

    def ipmitool_command(self, ipmitool_args):
        """ Execute an arbitrary ipmitool command """
        command = ["ipmitool", "-U", self.username, "-P", self.password, "-H",
                self.address]
        command += ipmitool_args

        self._vwrite(2, "Running %s\n" % " ".join(command))
        subprocess.call(command)

    def _get_update_plan(self, images, slot_arg):
        """ Get an update plan.

        A plan consists of a list of tuples:
        (image, slot, version) """
        plan = []

        # Get all slots
        try:
            slots = [x for x in self.bmc.get_firmware_info()
                    if hasattr(x, "slot")]
        except IpmiError:
            raise CxmanageError("Failed to retrieve firmware info")
        if not slots:
            raise CxmanageError("Failed to retrieve firmware info")

        soc_plan_made = False
        cdb_plan_made = False
        for image in images:
            if soc_plan_made and image.type == "CDB":
                for update in plan:
                    if update[0].type == "SOC_ELF":
                        slot = slots[int(update[1].slot) + 1]
                        plan.append((image, slot, update[2]))
            elif cdb_plan_made and image.type == "SOC_ELF":
                for update in plan:
                    if update[0].type == "CDB":
                        slot = slots[int(update[1].slot) - 1]
                        plan.append((image, slot, update[2]))
            else:
                # Filter slots for this type
                type_slots = [x for x in slots if
                        x.type.split()[1][1:-1] == image.type]
                if len(type_slots) < 1:
                    raise CxmanageError("No slots found on host")

                versions = [int(x.version, 16) for x in type_slots]
                versions = [x for x in versions if x != 0xFFFF]
                new_version = 0
                if len(versions) > 0:
                    new_version = min(0xffff, max(versions) + 1)

                if slot_arg == "FIRST":
                    plan.append((image, type_slots[0], new_version))
                elif slot_arg == "SECOND":
                    if len(type_slots) < 2:
                        raise CxmanageError("No second slot found on host")
                    plan.append((image, type_slots[1], new_version))
                elif slot_arg == "THIRD":
                    if len(type_slots) < 3:
                        raise CxmanageError("No third slot found on host")
                    plan.append((image, type_slots[2], new_version))
                elif slot_arg == "BOTH":
                    if len(type_slots) < 2:
                        raise CxmanageError("No second slot found on host")
                    plan.append((image, type_slots[0], new_version))
                    plan.append((image, type_slots[1], new_version))
                elif slot_arg == "OLDEST":
                    # Choose second slot if both are the same version
                    if (len(type_slots) == 1 or
                            type_slots[0].version < type_slots[1].version):
                        slot = type_slots[0]
                    else:
                        slot = type_slots[1]
                    plan.append((image, slot, new_version))
                elif slot_arg == "NEWEST":
                    # Choose first slot if both are the same version
                    if (len(type_slots) == 1 or
                            type_slots[0].version >= type_slots[1].version):
                        slot = type_slots[0]
                    else:
                        slot = type_slots[1]
                    plan.append((image, slot, new_version))
                elif slot_arg == "INACTIVE":
                    # Get inactive slots
                    inactive_slots = [x for x in type_slots if x.in_use != "1"]
                    if len(inactive_slots) < 1:
                        raise CxmanageError("No inactive slots found on host")

                    # Choose second slot if both are the same version
                    if (len(inactive_slots) == 1 or inactive_slots[0].version
                            < inactive_slots[1].version):
                        slot = inactive_slots[0]
                    else:
                        slot = inactive_slots[1]
                    plan.append((image, slot, new_version))
                else:
                    raise ValueError("Invalid slot argument")

                if image.type == "SOC_ELF":
                    soc_plan_made = True
                elif image.type == "CDB_ELF":
                    cdb_plan_made = True

        return plan

    def _update_image(self, work_dir, tftp, image, slot, new_version):
        """ Update a single image. This includes uploading the image,
        performing the firmware update, crc32 check, and activation."""
        tftp_address = "%s:%s" % (tftp.get_address(self.address),
                tftp.get_port())

        # Upload image to tftp server
        filename = image.upload(work_dir, tftp, slot, new_version)

        # Send firmware update command
        slot_id = int(slot.slot)
        image_type = image.type
        result = self.bmc.update_firmware(filename,
                slot_id, image_type, tftp_address)
        handle = result.tftp_handle_id

        # Wait for update to finish
        while True:
            time.sleep(1)
            self._vwrite(1, ".")
            result = self.bmc.get_firmware_status(handle)
            if not hasattr(result, "status"):
                raise CxmanageError("Unable to retrieve transfer info")
            if result.status != "In progress":
                break

        # Activate firmware on completion
        if result.status == "Complete":
            # Verify crc
            result = self.bmc.check_firmware(slot_id)
            if hasattr(result, "crc32") and not result.error != None:
                # Activate
                self.bmc.activate_firmware(slot_id)
            else:
                raise CxmanageError("Node reported crc32 check failure")
        else:
            raise CxmanageError("Node reported transfer failure")

    def _vwrite(self, verbosity, text):
        """ Write to stdout if we're at the right verbosity level """
        if self.verbosity == verbosity:
            sys.stdout.write(text)
            sys.stdout.flush()
