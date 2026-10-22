# 加载prompts.yaml中的prompt配置
import yaml
from pathlib import Path

# 加载指定路径文件的函数
def _load_yaml(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 加载项目中的yaml配置文件
_yaml_path = Path(__file__).parents[1] / 'prompt/prompts.yaml'
_config = _load_yaml(_yaml_path)

# 主agent配置
main_agent_config = _config['main_agent']
# 所有子agent配置
sub_agents_config = _config['sub_agents']

if __name__ == '__main__':
    print(_config)
    print(main_agent_config)
    print(sub_agents_config)