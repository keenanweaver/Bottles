import os
import uuid
import yaml
import shutil
import subprocess
from glob import glob
from typing import NewType

from ..utils import UtilsLogger
from .runner import Runner
from .manager_utils import ManagerUtils
from .globals import Paths, Samples
from .diff import Diff


logging = UtilsLogger()
BottleConfig = NewType('BottleConfig', dict)


class LayersStore:

    @staticmethod
    def list() -> list:
        '''
        List all layers in the layers directory.
        '''
        for f in glob(f"{Paths.layers}/*"):
            if os.path.isdir(f):
                yield f
        
    @staticmethod
    def get(name: str=None, uuid: str=None) -> dict:
        '''
        Get a layer by its name or uuid and return
        its config as a dict.
        '''
        if name:
            pattern = f"{Paths.layers}/@__{name}__*"
        elif uuid:
            pattern = f"{Paths.layers}/@__*__{uuid}"
        else:
            raise Exception("No layer name or uuid provided.")
        
        for f in glob(pattern):
            if os.path.isdir(f):
                layer = f
                break
        
        if layer:
            with open(f"{layer}/layer.yml", "r") as f:
                conf = yaml.safe_load(f)
                return conf

        raise Exception(f"No layer match pattern {pattern}.")


class Layer:

    '''
    (WIP) This feature is not yet implemented.
    ---
    Concept:
    - bottle = Bottle.new() | create a new bottle and return its config
    - layer = Layer.new("dotnet48") | create a new empty layer (@__dotnet48__uuid)
    - layer.mount_bottle(bottle) | link the bottle to the layer
    - Dependency.install(layer.config) | install dependency on layer
    - layer.sweep() | unlink bottle files from layer
    - layer.save() | create a index.yml file with stored files and hashes
    - layer = Layer.new("epic") | create a new empty layer (@__epic__uuid)
    - layer.mount_bottle(bottle) | link the bottle to the layer
    - layer.mount("dotnet48") | link dotnet48 layer files to the epic layer
    - Installer.run(layer.config) | launch epic installer on layer
    - layer.sweep() | unlink dependency and bottle layers files from layer
    - layer.save() | create a index.yml file with stored files and hashes
    - bottle.add_layer_entry(..) | add a new executable to bottle Layers
    
    Notes:
    - directories are not symlinked to avoid the new layer files to be created in the bottle directory
    - layers should be able to be mounted to other layers
    - layers should remembed other mounted layers, so that they can be unlinked when unmounting
    - layers need an index.yml file to store the files and hashes
    - layers paths need a uuid to avoid collisions, format: @__<name>__<uuid>
    - bottles should store layers as by entry point (programs/executables):
        - Layers:
            - uuid
                - name: <name>
                - exec_path: <exec_path> (C:\Program Files\Epic\Epic.exe)
                - exec_args: <exec_args> (--args)
                - exec_env:
                    - <name>: <value>
                - exec_cwd: <exec_cwd> (C:\Program Files\Epic)
                - parameters:
                    - <name>: <value> (dxvk: True)
    '''
    __uuid: str = None
    __path: str = None
    __mounts: list = None
    __config: dict = None
    runtime_conf: dict = None

    def new(self, name: str):
        '''
        Generate a new layer path based on the layer name
        and a random uuid. Also create a runtime config which
        is just a sample bottle config to be used by the
        manager to treat the layer as a bottle, plus the
        layer config.
        '''
        logging.info("Creating a new layer …")

        self.__uuid = str(uuid.uuid4())
        folder = f"@__{name}__{self.__uuid}"
        self.__path = f"{Paths.layers}/{folder}"

        _conf = Samples.config.copy()
        _conf["Path"] = f"@__{self.__uuid}"
        _conf["IsLayer"] = True # will be used by Dependency/Installer managers to set the right path

        shutil.makedirs(self.__path)

        self.runtime_conf = _conf
        self.__config = {
            "Name": name,
            "UUID": self.__uuid,
            "Path": f"@__{self.__uuid}",
            "Tree": {},
        }
    
    def __link_files(self, path):
        for root, dirs, files in os.walk(path):
            for f in files:
                _source = os.path.join(root, f)
                _layer = _source.replace(path, self.__path)
                os.makedirs(os.path.dirname(_layer), exist_ok=True) # should not be ok, need handling
                os.symlink(_source, _layer)

    def mount_dir(self, path: str, name: str = None):
        '''
        This method will mount a directory (which is not a layer)
        to the current layer and append it to the __mounts list. This
        should be use to mount external directories, use mount_bottle
        for bottles instead.
        '''
        _name = name if name else os.path.basename(path)
        _uuid = str(uuid.uuid4())
        hashes = Diff.hashify(path)

        self.__mounts.append({
            "Name": _name,
            "UUID": _uuid,
            "Path": path,
            "Tree": hashes,
            "Type": "absDir",
        })
        self.__link_files(path)
    
    def mount(self, name: str=None, uuid: str = None):
        '''
        This method will mount a layer to the current layer and
        append it to the __mounts list.
        '''
        layer = LayersStore.get(name, uuid)
        if layer:
            layer["Type"] = "layer"
            self.__mounts.append(layer)
            self.__link_files(layer["Path"])

    def mount_bottle(self, config: BottleConfig):
        '''
        This is just a wrapper to mount_dir to get the bottle
        path and mount it to the current layer.
        '''
        _path = ManagerUtils.get_bottle_path(config)
        self.mount_dir(_path, config["Name"])
    
    def sweep(self) -> BottleConfig:
        '''
        This method will unlink all the files from the mounted
        layers and update layer tree with residues.
        '''
        for mount in self.__mounts:
            _tree = mount["Tree"]
            
            for f in _tree:
                os.unlink(f"{self.__path}/{f}")
                
            self.__mounts.remove(mount)
        
        self.__config["Tree"] = Diff.hashify(self.__path)
    
    def save(self):
        '''
        This method will save the layer config to the layer.yml file
        in the layer directory.
        '''
        with open(f"{self.__path}/layer.yml", "w") as f:
            yaml.dump(self.__config, f)
