import os
import importlib
import inspect
from typing import Dict, Tuple, Type
from apis.api import shockApiBase

def load_all_apis(apis_folder: str = "apis") -> Dict[str, Tuple[str, Type[shockApiBase]]]:
    api_classes = {}
    base_dir = os.path.dirname(os.path.abspath(__file__))
    apis_dir = os.path.join(base_dir, apis_folder)
    if not os.path.exists(apis_dir):
        print(f"[加载器] 文件夹不存在: {apis_dir}")
        return api_classes
    for item in os.listdir(apis_dir):
        item_path = os.path.join(apis_dir, item)
        if not os.path.isdir(item_path) or item.startswith("__"):
            continue
        main_py_path = os.path.join(item_path, "main.py")
        if not os.path.exists(main_py_path):
            print(f"[加载器] 跳过 {item}: 找不到 main.py")
            continue
        module_path = f"{apis_folder}.{item}.main"
        
        try:
            module = importlib.import_module(module_path)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (issubclass(obj, shockApiBase) and 
                    obj is not shockApiBase and
                    hasattr(obj, 'ApiName')):
                    
                    api_name = getattr(obj, 'ApiName')
                    if api_name:
                        api_classes[api_name] = (item_path, obj)
                        print(f"[加载器] 加载API: {api_name} -> {module_path}.{name}")
                    else:
                        print(f"[加载器] 警告: {module_path}.{name} 未定义 ApiName")
                        
        except Exception as e:
            print(f"[加载器] 加载模块 {module_path} 失败: {e}")
    
    return api_classes

def create_api_instance(api_classes: Dict[str, Tuple[str, Type[shockApiBase]]], api_name: str, apis_folder: str = "apis"):
    if api_name not in api_classes:
        raise ValueError(f"未找到API: {api_name}，可用API: {list(api_classes.keys())}")
    api_class:Tuple[str, Type[shockApiBase]] = api_classes[api_name]
    return api_class[1](api_class[0])
def create_api_instances(api_classes: Dict[str, Tuple[str, Type[shockApiBase]]], api_names: list[str], apis_folder: str = "apis"):
    instances = []
    for api_name in api_names:
        instances.append(create_api_instance(api_classes, api_name, apis_folder))
    return instances