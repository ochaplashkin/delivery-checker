import json
import os
import shutil
import time

import requests

from classes.builders.docker import DockerBuilder, DockerInfo
from classes.builders.virtual_box import VirtualBoxBuilder, VirtualBoxInfo
from classes.results_sync import ResultsManager, Result


class Tester:
    def __init__(self, config_path='./config.json'):
        with open(config_path, 'r') as fs:
            config = json.load(fs)
            self.__parse_config(config)

        self.__logs = []
        self.__builds = None
        self.__all_builds = []

        self.__results_manager = ResultsManager(config, log_func=self.__log)

    def __parse_config(self, config):
        self.commands_url = config.get('commands_url', 'https://www.tarantool.io/api/tarantool/info/versions/')

        self.__install_dir = './install'
        self.__local_dir = './local'
        self.__logs_dir = f'{self.__local_dir}/logs'
        self.__results_dir = f'{self.__local_dir}/results'
        self.__results_file = f'{self.__local_dir}/results.json'

        os_params = config.get('os_params')
        assert config.get('os_params') is not None, 'No OS params in config!'

        self.__docker_params = {
            k: v['docker']
            for k, v in os_params.items()
            if v.get('docker') is not None
        }
        self.__virtual_box_params = {
            k: v['virtual_box']
            for k, v in os_params.items()
            if v.get('virtual_box') is not None
        }

    def __log(self, msg):
        self.__logs.append(msg)

    def __download_scripts(self, debug=False):
        site_commands = requests.get(self.commands_url).json()

        with open(os.path.join(self.__install_dir, 'default.sh'), mode='r') as fs:
            default_script = fs.read()

        builds = []
        for os_name, versions in site_commands.items():
            for build_name, commands in versions.items():
                # Remove os name from build name (ubuntu_manual_2.4 -> manual_2.4)
                build_name = '_'.join(build_name.split('_')[1:])

                # Save to find not tested
                self.__all_builds.append((os_name, build_name))

                builds_count = len(builds)

                # This is to avoid running Docker in Docker or Docker in VirtualBox
                if 'docker' not in os_name:
                    builds += DockerBuilder.get_builds(self.__docker_params, os_name, build_name)
                    builds += VirtualBoxBuilder.get_builds(self.__virtual_box_params, os_name, build_name)

                # Find name of image in commands and use it
                else:
                    builds += DockerBuilder.get_docker_builds(self.__docker_params, os_name, build_name, commands)
                    commands = []

                if len(builds) == builds_count and debug:
                    print(f'OS: {os_name}. Build: {build_name}. {Result.NO_TEST.value}')

                path = os.path.join(self.__install_dir, f'{os_name}_{build_name}.sh')
                with open(path, mode='w') as fs:
                    fs.write(default_script)
                    fs.write('\n'.join(commands))
                    fs.write('\n')

        return builds

    def test_builds(self):
        shutil.rmtree(self.__local_dir, ignore_errors=True)

        os.makedirs(self.__results_dir)
        os.makedirs(self.__logs_dir)

        self.__results = {}
        self.__builds = self.__builds or self.__download_scripts()
        for build in self.__builds:
            self.__logs.clear()

            if isinstance(build, DockerInfo):
                os_name = f'{build.os_name}_{build.image_version}'
            elif isinstance(build, VirtualBoxInfo):
                os_name = f'{build.vm_name}'
            else:
                os_name = build.os_name

            log_prefix = f'OS: {os_name}. Build: {build.build_name}.'
            print(f'\r{log_prefix} Running...', end='')
            self.__results[os_name] = self.__results.get(os_name, {})
            start = time.time()

            if build.skip:
                result = Result.SKIP
            else:
                if isinstance(build, DockerInfo):
                    docker_builder = DockerBuilder(build, log_func=self.__log)
                    deploy_result = docker_builder.deploy()
                elif isinstance(build, VirtualBoxInfo):
                    virtual_box_builder = VirtualBoxBuilder(build, log_func=self.__log)
                    deploy_result = virtual_box_builder.deploy()
                else:
                    deploy_result = False

                path = os.path.join(self.__logs_dir, f'{os_name}_{build.build_name}.log')
                with open(path, mode='w') as fs:
                    logs = '\n'.join(map(lambda x: str(x), self.__logs))
                    fs.write(logs)

                if deploy_result:
                    result = Result.OK
                else:
                    result = Result.ERROR
                    logs = logs.lower()
                    if 'timeout' in logs or 'timed out' in logs:
                        result = Result.TIMEOUT

            if result == Result.OK:
                is_results_ok = False

                path = os.path.join(self.__results_dir, f'{os_name}_{build.build_name}.json')
                if os.path.exists(path):
                    with open(path) as fs:
                        try:
                            build_results = json.load(fs)
                            is_results_ok = all(map(
                                lambda build_res: build_res == 'OK',
                                build_results.values(),
                            ))
                        except Exception:
                            pass

                if not is_results_ok:
                    result = Result.FAIL

            print(f'\r{log_prefix} Elapsed time: {time.time() - start:.2f}. {result.value}')
            self.__results[os_name][build.build_name] = result

        with open(self.__results_file, mode='w') as fs:
            fs.write(json.dumps(self.__results))

    def find_lost_results(self):
        self.__builds = self.__builds or self.__download_scripts()
        return self.__results_manager.find_lost_results(self.__all_builds)

    def sync_results(self):
        self.__builds = self.__builds or self.__download_scripts()
        return self.__results_manager.sync_results(self.__all_builds)

    def archive_results(self):
        return self.__results_manager.archive_results()

    def is_results_ok(self):
        return self.__results_manager.is_results_ok()
