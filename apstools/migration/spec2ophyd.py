#!/usr/bin/env python

"""
read SPEC config file and convert to ophyd setup commands

output of ophyd configuration to stdout
"""


from collections import OrderedDict
import re


CONFIG_FILE = 'config-8idi'
KNOWN_DEVICES = "PSE_MAC_MOT VM_EPICS_M1 VM_EPICS_PV VM_EPICS_SC".split()


class Spec2ophydBase(object):

    str_keys = []

    def obj_keys_to_list(self):
        items = []
        for k in self.str_keys:
            v = self.__getattribute__(k)
            if v is not None:
                items.append(f"{k}='{v}'")
        return items
    
    def __str__(self):
        items = self.obj_keys_to_list()
        return f"{self.__class__.__name__}({', '.join(items)})"


class SpecDevice(Spec2ophydBase):
    """
    SPEC configuration of a device, such as a multi-channel motor controller
    
    SPEC "devices" are components which counters or motors to controllers
    """
    
    def __init__(self, config_text):
        """parse the line from the SPEC config file"""
        self.raw = config_text
        # VM_EPICS_M1    = 9idcLAX:m58:c0: 8
        nm, args = config_text.split("=")
        self.name = nm.strip()
        prefix, num_channels = args.split()
        self.prefix = prefix
        self.config_line = None
        self.index = None
        self.num_channels = int(num_channels)
        self.ophyd_device = None
        self.str_keys = "config_line name index, prefix num_channels".split()


class ItemNameBase(Spec2ophydBase):
    
    ignore = False
    str_keys = "mne config_line name"

    def item_name_value(self, item):
        if hasattr(self, item):
            return f"{item}={self.__getattribute__(item)}"
    
    def ophyd_config(self):
        return f"{self.mne} = {self} # FIXME: not valid ophyd"


class SpecSignal(ItemNameBase):
    """
    SPEC configuration of a single EPICS PV
    """
    
    def __init__(self, mne, nm, pvname, config_text):
        """data provided by caller"""
        self.raw = config_text
        self.mne = mne
        self.name = nm
        self.pvname = pvname
        self.signal_name = "EpicsSignal"
        self.str_keys = "mne config_line name pvname signal_name".split()
    
    def ophyd_config(self):
        s = f"{self.mne} = {self.signal_name}('{self.pvname}', name='{self.mne}')"
        if self.mne != self.name:
            s += f"  # {self.name}"
        if self.ignore:
            s = "# NONE: " + s
        return s


class SpecMotor(ItemNameBase):
    """
    SPEC configuration of a motor channel
    """
    
    def __init__(self, config_text):
        """parse the line from the SPEC config file"""
        self.raw = config_text
        # Motor    ctrl steps sign slew base backl accel nada  flags   mne  name
        # MOT002 = EPICS_M2:0/3   2000  1  2000  200   50  125    0 0x003       my  my
        lr = config_text.split(sep="=", maxsplit=1)
        self.config_line = int(lr[0].strip("MOT"))
        
        def pop_word(line, int_result=False):
            line = line.strip()
            pos = line.find(" ")
            l, r = line[:pos].strip(), line[pos:].strip()
            if int_result:
                l = int(l)
            return l, r
        
        self.ctrl, r = pop_word(lr[1])
        self.steps, r = pop_word(r, True)
        self.sign, r = pop_word(r, True)
        self.slew, r = pop_word(r, True)
        self.base, r = pop_word(r, True)
        self.backl, r = pop_word(r, True)
        self.accel, r = pop_word(r, True)
        self.nada, r = pop_word(r, True)
        self.flags, r = pop_word(r)
        self.mne, self.name = pop_word(r)
        self.device = None
        self.pvname = None
        self.motpar = []
        self.macro_prefix = None
        self.str_keys = "mne config_line name macro_prefix".split()
    
    def __str__(self):
        items = self.obj_keys_to_list()
        txt = self.item_name_value("pvname") or self.item_name_value("ctrl")
        if not txt.endswith("=None"):
            items.append(txt)
        return f"{self.__class__.__name__}({', '.join(items)})"
    
    def setDevice(self, devices):
        if self.ctrl.startswith("EPICS_M2"):
            device_list = devices.get("VM_EPICS_M1")
            if device_list is not None:
                uc_str = self.ctrl[len("EPICS_M2:"):]
                unit, chan = list(map(int, uc_str.split("/")))
                self.device = device_list[unit]
                self.pvname = "{}m{}".format(self.device.prefix, chan)
        elif self.ctrl.startswith("MAC_MOT"):
            device_list = devices.get("PSE_MAC_MOT")
            if device_list is not None:
                uc_str = self.ctrl[len("MAC_MOT:"):]
                unit, chan = list(map(int, uc_str.split("/")))
                self.device = device_list[unit]
                self.macro_prefix = self.device.prefix
                # TODO: what else?
        elif self.ctrl.startswith("NONE"):
            self.ignore = True
    
    def ophyd_config(self):
        s = f"{self.mne} = EpicsMotor('{self.pvname}', name='{self.mne}')"
        if self.pvname is None:
            if self.macro_prefix is not None:
                s = f"# Macro Motor: {self}"
            else:
                s = f"# line {self.config_line}: {self.raw}"
        if self.mne != self.name:
            s += f"  # {self.name}"
        if len(self.motpar) > 0:
            s += f" # {', '.join(self.motpar)}"
        return s



class SpecCounter(ItemNameBase):
    """
    SPEC configuration of a counter channel
    
    In SPEC's config file, a single PV signal is described as a counter,
    attached to an EPICS_PV (as described by a VM_EPICS_PV device).
    """
    
    def __init__(self, config_text):
        """parse the line from the SPEC config file"""
        self.raw = config_text
        # # Counter   ctrl unit chan scale flags    mne  name
        # CNT000 = EPICS_SC  0  0 10000000 0x001      sec  seconds

        def pop_word(line, int_result=False):
            line = line.strip()
            pos = line.find(" ")
            l, r = line[:pos].strip(), line[pos:].strip()
            if int_result:
                l = int(l)
            return l, r

        l, r = pop_word(config_text)
        self.config_line = int(l.strip("CNT"))
        l, r = pop_word(r)      # ignore "="
        self.ctrl, r = pop_word(r)
        self.unit, r = pop_word(r, True)
        self.chan, r = pop_word(r, True)
        self.scale, r = pop_word(r, True)
        self.flags, r = pop_word(r)
        self.mne, self.name = pop_word(r)
        self.device = None
        self.pvname = None
        self.reported_pvs = []
        self.str_keys = "mne config_line name unit chan".split()

    def __str__(self):
        items = self.obj_keys_to_list()
        txt = self.item_name_value("pvname")
        if txt is not None:
            items.append(txt)
        else:
            items.append(self.item_name_value("ctrl"))
        return f"{self.__class__.__name__}({', '.join(items)})"
    
    def setDevice(self, devices):
        if self.ctrl.startswith("EPICS_SC"):
            device_list = devices.get("VM_EPICS_SC")
            if device_list is not None:
                self.device = device_list[self.unit]
                # scalers are goofy, SPEC uses 0-based numbering, scaler uses 1-based
                self.pvname = "{}.S{}".format(self.device.prefix, self.chan+1)
        elif self.ctrl.startswith("EPICS_PV"):
            device_list = devices.get("VM_EPICS_PV")
            if device_list is not None:
                self.device = device_list[self.unit]
                self.pvname = self.device.prefix
                self.ophyd_device = "EpicsSignal"
        elif self.ctrl.startswith("NONE"):
            self.ignore = True
    
    def ophyd_config(self):
        s = f"# counter: {self.mne} = {self}"
        if self.ignore:
            s = f"# line {self.config_line}: {self.raw}"
        return s


class SpecConfig(object):
    """
    SPEC configuration
    """
    
    def __init__(self, config_file):
        self.config_file = config_file or CONFIG_FILE
        self.devices = OrderedDict()
        self.scalers = []
        self.collection = []
        self.unhandled = []
    
    def read_config(self, config_file=None):
        self.config_file = config_file or self.config_file
        motor = None
        with open(self.config_file, 'r') as f:
            for line_number, line in enumerate(f.readlines()):
                line = line.strip()

                if line.startswith("#"):
                    continue

                word0 = line.split(sep="=", maxsplit=1)[0].strip()
                if word0 in KNOWN_DEVICES:
                    device = SpecDevice(line)
                    if device.name not in self.devices:
                        self.devices[device.name] = []
                    # 0-based numbering
                    device.config_line = line_number
                    device.index = len(self.devices[device.name])
                    self.devices[device.name].append(device)
                elif word0.startswith("MOTPAR:"):
                    if motor is not None:
                        motor.motpar.append(line[len("MOTPAR:"):])
                elif re.match("CNT\d*", line) is not None:
                    counter = SpecCounter(line)
                    counter.setDevice(self.devices)
                    if counter.ctrl == "EPICS_PV":
                        signal = SpecSignal(counter.mne, counter.name, counter.pvname, line)
                        self.collection.append(signal)
                    else:
                        if counter.pvname is not None:
                            pvname = counter.pvname.split(".")[0]
                            if pvname not in self.scalers:
                                mne = pvname.lower().split(":")[-1]
                                scaler = SpecSignal(mne, mne, pvname, line)
                                scaler.signal_name = "ScalerCH"
                                self.scalers.append(pvname)
                                self.collection.append(scaler)
                        
                        self.collection.append(counter)
                elif re.match("MOT\d*", line) is not None:
                    motor = SpecMotor(line)
                    motor.setDevice(self.devices)
                    self.collection.append(motor)
                else:
                    self.unhandled.append(line)


def create_ophyd_setup(spec_config):
    for device in spec_config.collection:
        print(f"{device.ophyd_config()}")


def main():
    spec_cfg = SpecConfig(CONFIG_FILE)
    spec_cfg.read_config()
    create_ophyd_setup(spec_cfg)


if __name__ == "__main__":
    main()