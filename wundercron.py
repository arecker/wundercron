# -*- coding: utf-8 -*-

"""Automatically create wunderlist todo's."""

import argparse
import collections
import configparser
import datetime
import json
import logging
import os
import subprocess
import time
import urllib.parse
import urllib.request


def make_logger():
    logger = logging.getLogger('wundercron')
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


logger = None
Creds = collections.namedtuple('Creds', 'client_id client_token')
Cron = collections.namedtuple('Cron', 'minute hour day month weekday')


def make_request(path, method='GET', creds=None, params={}, data={}):
    url = 'https://a.wunderlist.com/api/v1/'

    if path.startswith('/'):
        path = path[1:]

    url = urllib.parse.urljoin(url, path)
    headers = {'Content-Type': 'application/json'}

    if creds:
        headers.update({
            'X-Access-Token': creds.client_token,
            'X-Client-ID': creds.client_id
        })

    if params:
        url += '?{}'.format(urllib.parse.urlencode(params))

    request = urllib.request.Request(url, headers=headers, method=method)

    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
            try:
                return response.status, json.loads(body)
            except ValueError:
                return response.status, body.decode()
    except urllib.error.HTTPError as e:
        try:
            return e.status, json.loads(e.read().decode())
        except ValueError:
            raise e


def shell_out(command):
    command_list = command.split(' ')
    process = subprocess.run(command_list, stdout=subprocess.PIPE)
    return process.stdout.decode().strip()


def make_creds(config):
    id_command = config.get('wundercron', 'client_id_command')
    secret_command = config.get('wundercron', 'client_secret_command')
    client_id = shell_out(id_command)
    client_secret = shell_out(secret_command)
    return Creds(client_id, client_secret)


def get_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', '-c', help='path to wundercron config', default='~/.wundercron.cfg')
    parser.add_argument('--verbose', '-v', action='store_true', help='print debug logs', default=False)
    parser.add_argument('--quiet', '-q', action='store_true', help='hide all output', default=False)
    parser.add_argument('--interval', '-i', type=int, help='seconds to wait between checks', default=60)
    return parser.parse_args()


class InvalidCron(Exception):
    pass


class Task(object):
    InvalidCron = InvalidCron

    @classmethod
    def list_from_config(cls, config, now=None, creds=None):
        sections = config.sections()
        excluded = ['wundercron', 'defaults']
        return [
            cls(sec, cron=config[sec]['cron'], now=now, creds=creds)
            for sec
            in sections
            if sec not in excluded
        ]

    def __init__(self, name, cron='', now=None, creds=None):
        self.name = name
        self.cron = cron
        self.now = now
        self.creds = creds

    def __repr__(self):
        return '<Task {}>'.format(self.name)

    def activated(self):
        try:
            cron = Cron(*[s.strip() for s in self.cron.split(' ')])
        except TypeError:
            raise self.InvalidCron('"{}" is invalid'.format(self.cron))

        for field in ('minute', 'hour', 'day', 'month', 'weekday'):
            expr = getattr(cron, field)
            value = getattr(self.now, field)

            if hasattr(value, '__call__'):
                value = value()  # weekday is a function

            try:
                if expr in ['*', '?']:
                    continue
                elif '/' in expr:
                    _, divisor = expr.split('/')
                    assert value % int(divisor) == 0
                elif '-' in expr:
                    beg, end = expr.split('-')
                    assert int(beg) <= value <= int(end)
                else:
                    assert int(expr) <= value
            except AssertionError:
                return False

        return True


def main():
    args = get_args()
    logger = make_logger()

    if args.quiet:
        logger.handlers = []
    elif args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.debug('received args %s', vars(args))

    config = configparser.ConfigParser()

    while True:
        now = datetime.datetime.now()
        logger.debug('reading config from %s', args.config)
        config.read(os.path.expanduser(args.config))
        creds = make_creds(config)
        tasks = Task.list_from_config(config, now=now, creds=creds)

        if tasks:
            logger.info('found %s task(s) to process', len(tasks))
            for task in tasks:
                if task.activated():
                    logger.info('%s - creating', task.name)
                else:
                    logger.info('%s - not yet activated')
        else:
            logger.debug('no tasks found')

        logger.debug('waiting %s seconds before checking again', args.interval)
        time.sleep(args.interval)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info('exiting')
