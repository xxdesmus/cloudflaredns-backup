#!/usr/bin/env python3
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from os import makedirs, path
from requests import Session
from datetime import datetime

import logging

__author__ = 'm_messiah'
VERSION = "1.0"


class CloudFlareDns(object):
    def __init__(self, email, token, zones):
        self.conn = Session()
        self.conn.headers = {
            'X-Auth-Email': email,
            'X-Auth-Key': token,
        }
        self.url = "https://api.cloudflare.com/client/v4/"
        self.zones = self.get_zones(zones)

    def get_pages(self, url):
        result = []
        logging.debug("Fetch %s" % url)
        try:
            resp = self.conn.get(self.url + url)
            if resp.status_code != 200:
                logging.error("Error in fetching. url=%s status_code=%s"
                              % (url, resp.status_code))
                return result
            resp = resp.json()
            result.extend(resp['result'])
            total_pages = resp['result_info']['total_pages']
            if total_pages > 1:
                logging.debug("Found %s pages on CloudFlare" % total_pages)
                for page in range(2, total_pages + 1):
                    resp = self.conn.get(self.url + url, params={'page': page})
                    if resp.status_code != 200:
                        logging.error(
                            "Error in fetching. url=%s page=%s status_code=%s"
                            % (url, page, resp.status_code)
                        )
                        break
                    result.extend(resp.json()['result'])
        except Exception as error:
            logging.warning("Error while fetching %s: %s" % (url, error))
        finally:
            return result

    def get_zones(self, zones):
        return {
            zone['name']: self.get_pages("zones/%s/dns_records" % zone['id'])
            for zone in self.get_pages("zones")
            if zone['name'] in zones or not zones
        }

    def bindify(self, zone):
        timestamp = datetime.now()
        result = [
            ';; Domain: %s' % zone,
            ';; Exported: %s' % timestamp.strftime("%Y-%m-%d %H:%M"),
            '$ORIGIN %s.' % zone,
            """@\t300\tSOA\t%s. hostmaster.%s. (
                                %s ; Serial
                                28800   ; Refresh
                                7200    ; Retry
                                604800  ; Expire
                                300)    ; Minimum TTL
            """ % (zone, zone, timestamp.strftime("%Y%m%d%H%M")),
        ]
        for rec in self.zones[zone]:
            content = rec['content']
            if rec['type'] in {'SPF', 'TXT'}:
                content = "\"" + content + "\""
            elif rec['type'] == 'CNAME':
                content += "."
            elif rec['type'] == 'MX':
                content = '\t'.join((str(rec['priority']), content))
            result.append("\t".join((
                rec['name'] + ".",
                "300" if rec['ttl'] == 1 else str(rec['ttl']),
                "IN",
                rec['type'],
                content
            )))
        return "\n".join(result)


def backup_dns(email, token, zones, output):
    cloudflare = CloudFlareDns(email, token, zones)
    if output:
        makedirs(output, exist_ok=True)
        for zone in cloudflare.zones:
            with open(path.join(output, zone), "w") as bind_file:
                bind_file.write(cloudflare.bindify(zone))
    else:
        for zone in cloudflare.zones:
            print(cloudflare.bindify(zone))
            print()


if __name__ == '__main__':
    parser = ArgumentParser(
        description="Backup CloudFlare DNS zones as files for BIND",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""EXAMPLES:

    %(prog)s root@example.com 1234567890
        get all your CloudFlare zones to console

    %(prog)s root@example.com 1234567890 -z example.com -z example2.com
        get only example.com and example2.com zones.
        This example may be simplified as:
        %(prog)s root@example.com 1234567890 -z "example1.com example2.com"

    %(prog)s root@example.com 1234567890 -z example.com -o zones
        create if not exists folder and write zone to ./zones/example.com
        """
    )
    parser.add_argument("email", help="CloudFlare user email")
    parser.add_argument("token", help="CloudFlare API token")

    parser.add_argument("-z", "--zones", action="append",
                        help="List of exported zones (if omitted - export all)")

    parser.add_argument("-o", "--output",
                        help="Output directory for zones "
                             "(if omitted write zones to stdout)")
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('-v', '--verbose', action="store_true",
                        help="Show debug logging. "
                             "BE CAREFUL when use verbosity with STDOUT zones")
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.zones:
        args.zones = " ".join(args.zones).split()

    backup_dns(args.email, args.token, args.zones, args.output)