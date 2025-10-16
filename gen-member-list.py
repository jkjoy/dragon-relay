#!/usr/bin/env python

import logging
import requests
import base64
import os
import redis

from datetime import datetime, timezone
import multiprocessing

outfile = 'src/index.stx'
headers = '''---
title: DragonRelay
subtitle: Mastodon/Misskey/Pleroma中文中继
---

欢迎来到**DragonRelay**！

DragonRelay 是一款Activity Pub中继，支持Mastodon/Misskey/Pleroma等兼容ActivityPub的软件，欢迎各大实例管理员加入！

## 如何使用


::: infobox .warning
    Note: By subscribing to this relay, you acknowledge that this is a relay used solely among instances that post in Chinese. If your instance contains too many non-Chinese posts, it may be removed and blocked without any notice or explanation.

Mastodon 管理员可在后台设置中的“管理-中继-添加新中继”添加以下地址(其他与 Mastodon 兼容的 ActivityPub 实现也可能可以使用此地址):

::: span .code
    `https://relay.dragon-fly.club/inbox`

刷新后状态变为 Enabled 即代表成功添加并订阅本中继服务。如果状态长时间处于 Pending, 可能是订阅回调消息丢失，可以尝试删除后重新添加并启用。

如果是 Pleroma 或其他与其兼容的 ActivityPub 实现，则可以通过以下命令关注 (Follow) 中继:

::: span .code
    `MIX_ENV=prod mix pleroma.relay follow https://relay.dragon-fly.club/actor` 

## 不受欢迎的内容

设立此中继的初衷是希望促进中文用户间的交流，但鉴于中继本身放大信息流动的天然特性，有一些内容是不适合以此种形式传播的。

以下内容在本中继不受欢迎，大量发布、或主要发布涉及相关内容的实例将可能被移除转发列表并被屏蔽，且相关操作不会有任何事先告知：

  * 大量非中文内容
  * 大量非原创或无意义的转发、重复内容刷屏
  * 大量虚假内容、大量广告或其他商业目的的内容
  * 讨论政治、发表政见
  * 发布成人内容等不适合公开展示的内容
  * 血腥内容
  * 煽动暴力、宣扬恐怖主义
  * 针对他人的人身攻击、仇恨言论
  * 其他另人反感的内容

:!! 注意
    [中继管理员](https://mast.dragon-fly.club/@NotreMonde)保留判定任意给定内容或订阅实例是否合规、以及作出封禁决定的最终权利。

## 成员

以下为目前订阅了本中继服务的实例列表，列表每15分钟自动更新，并不完全反映最新的真实订阅情况，仅供参考。
'''


USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0 (https://relay.dragon-fly.club)'

instance_ids = set()

def read_redis_keys():
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    client = redis.from_url(redis_url, decode_responses=True)
    keys = client.keys('relay:subscription:*')
    return '\n'.join(keys)


def generate_instance_id(page):
    uid = []

    try:
        uid.append(page['uri'] if page['uri'] else '')
    except KeyError:
        pass
    try:
        uid.append(page['email'] if page['email'] else '')
    except KeyError:
        pass
    try:
        uid.append(page['contact_account']['id']
                   if page['contact_account'] else '')
        uid.append(page['contact_account']['username']
                   if page['contact_account'] else '')
    except KeyError:
        pass

    # misskey
    try:
        uid.append(page['name'] if page['name'] else '')
    except KeyError:
        pass
    try:
        uid.append(page['hcaptchaSiteKey'] if page['hcaptchaSiteKey'] else '')
    except KeyError:
        pass

    return '_'.join(uid)

def execute(line):
    _timeout = 4
    if not line or 'subscription' not in line:
        return
    domain = line.split('subscription:')[-1]

    headers = {
        'User-Agent': USER_AGENT
    }

    # query server meta
    try:
        md_line, uid = try_mastodon(headers, domain, _timeout)
        if uid in instance_ids:
            logger.info("Skipped duplicate domain %s" % domain)
            return
        instance_ids.add(uid)
        return md_line
    except Exception as e:
        try:
            md_line, uid = try_misskey(headers, domain, _timeout)
            if uid and uid in instance_ids:
                logger.info("Skipped duplicate domain %s" % domain)
            instance_ids.add(uid)
        except Exception as e:
            try:
                md_line, uid = try_nodeinfo(headers, domain, _timeout)
                if uid and uid in instance_ids:
                    logger.info("Skipped duplicate domain %s" % domain)
                instance_ids.add(uid)
            except Exception as e:
                md_line = '  * [%s](https://%s) | Stats Unavailable' % (domain, domain)
                logger.warning(e)
                return (md_line, 0)
        return md_line

def generate_list():
    def sortSecond(val):
        return val[1]

    pool = multiprocessing.Pool(8)
    md_list = [x for x in pool.map(execute, read_redis_keys().split('\n')) if x is not None]

    md_list.sort(key=sortSecond,reverse=True)
    return list(map( lambda i: i[0], md_list ))

def try_nodeinfo(headers, domain, timeout):
    url = "https://%s/.well-known/nodeinfo" % domain
    response = requests.get(url, headers=headers, timeout=timeout)
    if not response:
        response.raise_for_status()
    wellknown = response.json()
    for l in wellknown["links"]:
        if l["rel"] == 'http://nodeinfo.diaspora.software/ns/schema/2.0':
            nodeinfo_url = l["href"]
            break

    resp = requests.get(nodeinfo_url, headers=headers, timeout=timeout)
    if not resp:
        resp.raise_for_status()
    nodeinfo = resp.json()

    data = []

    try:
        data.append(nodeinfo["metadata"]["nodeName"] if nodeinfo["metadata"]["nodeName"] else '')
    except KeyError:
        pass
    try:
        data.append(nodeinfo["metadata"]["nodeDescription"] if nodeinfo["metadata"]["nodeDescription"] else '')
    except KeyError:
        pass
    try:
        data.append(nodeinfo['maintainer']['name'] if nodeinfo['maintainer'] else '')
        data.append(nodeinfo['maintainer']['email'] if nodeinfo['maintainer'] else '')
    except KeyError:
        pass

    uid = '_'.join(data)

    title = nodeinfo["metadata"]["nodeName"]
    version = nodeinfo["software"]["version"]
    software = nodeinfo["software"]["name"]
    stats = nodeinfo["usage"]
    #favicon = requests.get("https://%s/favicon.ico" % domain, headers=headers, timeout=timeout)
    #if favicon.content:
    #    fav_md = '![icon for %s](data:image/x-icon;base64,%s)' % (title, base64.b64encode(favicon.content).decode('utf-8'))
    #else:
    #    fav_md = ''

    md_line = '  * %s | [%s](https://%s) | 👥 %s 💬 %s 📌 %s(%s)' % (title, domain, domain, stats['users']['total'], stats['localPosts'], software, version)
    return ( md_line, stats['users']['total'] ), uid
    
def try_mastodon(headers, domain, timeout):
    url = "https://%s/api/v1/instance" % domain
    response = requests.get(url, headers=headers, timeout=timeout)
    if not response:
        response.raise_for_status()
    page = response.json()

    uid = generate_instance_id(page)

    title = page['title']
    version = page['version']
    if "Firefish" in version or "Misskey" in version or "firefish" in version or "misskey" in version:
        raise "Firefish/Misskey"
        
    stats = page['stats']
    #favicon = requests.get("https://%s/favicon.ico" % domain, headers=headers, timeout=timeout)
    #if favicon.content:
    #    fav_md = '![icon for %s](data:image/x-icon;base64,%s)' % (title, base64.b64encode(favicon.content).decode('utf-8'))
    #else:
    #    fav_md = ''

    md_line = '  * %s | [%s](https://%s) | 👥 %s 💬 %s 🐘 %s 📌 Mastodon(%s)' % (title, domain, domain, stats['user_count'], stats['status_count'], stats['domain_count'], version)
    return ( md_line, stats['user_count'] ), uid


def try_misskey(headers, domain, timeout):
    url_meta = "https://%s/api/meta" % domain
    resp_meta = requests.post(url_meta, headers=headers, timeout=15)
    if not resp_meta:
        resp_meta.raise_for_status()
    meta = resp_meta.json()

    uid = generate_instance_id(meta)

    title = meta['name']
    version = meta['version']

    #favicon = requests.get("https://%s/favicon.ico" % domain, headers=headers, timeout=timeout)
    #if favicon.content:
    #    fav_md = '![icon for %s](data:image/x-icon;base64,%s)' % (title, base64.b64encode(favicon.content).decode('utf-8'))
    #else:
    #    fav_md = ''

    url_stats = "https://%s/api/stats" % domain
    resp_stats = requests.post(url_stats, headers=headers, timeout=15)
    if not resp_stats:
        md_line = '  * %s %s | [%s](https://%s) | 📌 %s' % (fav_md, title, domain, domain, version)
        return ( md_line, 0 ), uid
    stats = resp_stats.json()

    #md_line = '  * %s %s | [%s](https://%s) | 👥 %s 💬 %s 🐘 %s 📌 Misskey(%s)' % (fav_md, title, domain, domain, stats['originalUsersCount'], stats['originalNotesCount'], stats['instances'], version)
    md_line = '  * %s | [%s](https://%s) | 👥 %s 💬 %s 🐘 %s 📌 Misskey(%s)' % (title, domain, domain, stats['originalUsersCount'], stats['originalNotesCount'], stats['instances'], version)
    return ( md_line, stats['originalUsersCount'] ), uid


def write_file(filename, data, mode='w'):
    with open(filename, mode=mode, encoding='utf-8') as f:
        try:
            f.write(str(data, 'utf-8'))
        except TypeError:
            f.write(data)
    f.close()


if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    log_handler = logging.StreamHandler()
    log_handler.setLevel(logging.INFO)
    log_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s.')
    log_handler.setFormatter(log_format)
    logger.addHandler(log_handler)

    logger.info('Started generating member list.')
    sub_list = generate_list()
    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = 'Updated %s instances at: %s %s' % (len(sub_list), curr_time, datetime.now(timezone.utc).astimezone().tzinfo)
    logger.info(date_str)
    footer = '''

👥 实例用户数，💬 实例消息数，🐘 实例互联数，📌 实例版本

%s

## 技术细节

本中继后端使用[Activity-Relay](https://github.com/yukimochi/Activity-Relay)，[前端页面](https://github.com/dragonfly-club/dragon-relay)使用Ark定时生成。

## 维护团队

Proudly by [DragonFly Club](https://dragon-fly.club/)
    ''' % date_str
    full_page = '%s\n%s\n\n%s\n' % (
        headers, '\n'.join(sub_list), footer)
    write_file(outfile, full_page)
    logger.info('Write new page template done.')
