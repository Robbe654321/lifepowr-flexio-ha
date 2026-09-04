# Security

## What this integration touches

It makes unauthenticated HTTP requests to one host on your local network, the
one you configure. It sends nothing anywhere else, stores no credentials, and
has no cloud component.

## What you should know about the FlexiO API

**The box's API has no authentication.** That is the vendor's design, not a
choice made here. Anyone who can reach the box on your network can read every
measurement and set the generic load's price cap — with or without this
integration. If that matters to you, put the box on a segmented VLAN.

The API is also plain HTTP. Requests and responses cross your network in the
clear.

## Reporting a vulnerability in this integration

Open a [security advisory][advisory] rather than a public issue. Include what
an attacker would need to be able to do, and what they would gain.

Vulnerabilities in the FlexiObox itself belong with
[LIFEPOWR](https://flexio.lifepowr.io/support/help-center), not here.

## Supported versions

The latest release. This is a single-maintainer project; older versions get no
backports.

[advisory]: https://github.com/Robbe654321/lifepowr-flexio-ha/security/advisories/new
