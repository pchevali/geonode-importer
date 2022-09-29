import json
import logging
import os
from geonode.utils import get_supported_datasets_file_types
from geonode.resource.enumerator import ExecutionRequestAction as exa
from geonode.upload.utils import UploadLimitValidator
from importer.handlers.common.vector import BaseVectorFileHandler
from osgeo import ogr
from pathlib import Path

from importer.handlers.shapefile.exceptions import InvalidShapeFileException
from importer.handlers.shapefile.serializer import ShapeFileSerializer

logger = logging.getLogger(__name__)


class ShapeFileHandler(BaseVectorFileHandler):
    """
    Handler to import GeoJson files into GeoNode data db
    It must provide the task_lists required to comple the upload
    """

    ACTIONS = {
        exa.IMPORT.value: (
            "start_import",
            "importer.import_resource",
            "importer.publish_resource",
            "importer.create_geonode_resource",
        ),
        exa.COPY.value: (
            "start_copy",
            "importer.copy_dynamic_model",
            "importer.copy_geonode_data_table",
            "importer.publish_resource",
            "importer.copy_geonode_resource"
        ),
    }

    @staticmethod
    def can_handle(_data) -> bool:
        """
        This endpoint will return True or False if with the info provided
        the handler is able to handle the file or not
        """
        base = _data.get("base_file")
        if not base:
            return False
        ext = base.split(".")[-1] if isinstance(base, str) else base.name.split(".")[-1]
        return ext in ["shp"]

    @staticmethod
    def has_serializer(data) -> bool:
        _base = data.get("base_file")
        if not _base:
            return False
        if _base.endswith("shp") if isinstance(_base, str) else _base.name.endswith("shp"):
            return ShapeFileSerializer
        return False

    @staticmethod
    def extract_params_from_data(_data, action=None):
        """
        Remove from the _data the params that needs to save into the executionRequest object
        all the other are returned
        """
        if action == exa.COPY.value:
            title = json.loads(_data.get("defaults"))
            return {"title": title.pop("title")}, _data

        additional_params = {
            "skip_existing_layers": _data.pop("skip_existing_layers", "False"),
            "override_existing_layer": _data.pop("override_existing_layer", "False"),
            "store_spatial_file": _data.pop("store_spatial_files", "True"),
        }

        return additional_params, _data

    @staticmethod
    def is_valid(files, user):
        """
        Define basic validation steps:
        """
        # getting the upload limit validation
        upload_validator = UploadLimitValidator(user)
        upload_validator.validate_parallelism_limit_per_user()

        _file = files.get("base_file")
        if not _file:
            raise InvalidShapeFileException("base file is not provided")

        _filename = Path(_file).stem

        _shp_ext_needed = [
            x["requires"]
            for x in get_supported_datasets_file_types()
            if x["id"] == "shp"
        ][0]

        '''
        Check if the ext required for the shape file are available in the files uploaded
        by the user
        '''
        is_valid = all(
            map(
                lambda x: any(
                    _ext.endswith(f"{_filename}.{x}") if isinstance(_ext, str) else _ext.name.endswith(f"{_filename}.{x}")
                    for _ext in files.values()
                ),
                _shp_ext_needed,
            )
        )
        if not is_valid:
            raise InvalidShapeFileException(
                detail=f"Some file is missing files with the same name and with the following extension are required: {_shp_ext_needed}"
            )

        return True

    def get_ogr2ogr_driver(self):
        return ogr.GetDriverByName("ESRI Shapefile")

    @staticmethod
    def create_ogr2ogr_command(files, original_name, override_layer, alternate):
        '''
        Define the ogr2ogr command to be executed.
        This is a default command that is needed to import a vector file
        '''
    
        base_command = BaseVectorFileHandler.create_ogr2ogr_command(files, original_name, override_layer, alternate)
        layers = ogr.Open(files.get("base_file"))
        layer = layers.GetLayer(original_name)
        additional_option = " -nlt PROMOTE_TO_MULTI" if layer is not None and 'Point' not in ogr.GeometryTypeToName(layer.GetGeomType()) else " "
        return f"{base_command } -lco precision=no -lco GEOMETRY_NAME={BaseVectorFileHandler().default_geometry_column_name}" + additional_option

    def promote_to_multi(self, geometry_name):
        '''
        If needed change the name of the geometry, by promoting it to Multi
        example if is Point -> MultiPoint
        Needed for the shapefiles
        '''
        if 'Multi' not in geometry_name and 'Point' not in geometry_name:
            return f"Multi {geometry_name.title()}"
        return geometry_name