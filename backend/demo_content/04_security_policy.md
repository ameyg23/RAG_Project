# Information Security Policy — Acme Software Inc.

*Fictional demo content: an internal security policy for the fictional
Acme Software Inc.*

## Purpose

This policy describes the minimum security practices every Acme employee
and contractor must follow when handling company systems and data. It
applies to all company-owned devices and to any personal device used to
access Acme systems.

## Password Requirements

All Acme account passwords must be at least 12 characters long and must
not be reused from any other service. Acme provisions a password manager
license (1Password) to every employee and strongly recommends using it to
generate and store unique passwords for every system. Passwords must be
rotated immediately if you suspect they have been exposed; there is no
mandatory periodic rotation schedule otherwise, since forced periodic
rotation is no longer considered a security best practice.

## Two-Factor Authentication

Two-factor authentication (2FA) is mandatory for every Acme account,
including email, the HR portal, Beacon itself, and any connected
third-party tool that supports it. New hires must enable 2FA on their
Acme account before they can access any internal system, as part of
first-day setup. Acme supports authenticator-app-based 2FA (preferred) and
SMS-based 2FA as a fallback for employees without a compatible device.

## Acceptable Use of Company Devices

Company laptops are provided for work use but may be used for reasonable
personal tasks (checking personal email, browsing) provided this does not
interfere with work or introduce security risk. Installing software
outside of the approved software catalog requires IT approval.
Company devices must have full-disk encryption enabled, which is
configured automatically during device setup and must never be disabled.

## Data Classification and Handling

Acme classifies data into three tiers:

- **Public** — information already intended for public release (marketing
  materials, public documentation). No special handling required.
- **Internal** — information meant for Acme employees only (this
  handbook, internal roadmaps, non-public metrics). May be shared with
  contractors under NDA but must never be posted publicly.
- **Confidential** — customer data, employee personal information (PII),
  financial records, and security credentials. Confidential data may only
  be accessed by employees whose role requires it, must never be stored on
  a personal device or personal cloud storage account, and must be
  encrypted both at rest and in transit.

## Incident Reporting

Any suspected security incident — a lost or stolen device, a phishing
email you clicked, unusual account activity, or a suspected data leak —
must be reported to security@acme-demo.example within 24 hours of
discovery. There is no penalty for reporting a mistake in good faith;
the goal is fast containment, not blame. Security will acknowledge every
report within 1 business hour during business hours, and within 4 hours
outside business hours for anything marked urgent.

## Remote Work Security Requirements

Employees working remotely must connect to internal systems only over the
company VPN when accessing anything classified as Confidential. Public
Wi-Fi networks (cafes, airports, hotels) may be used for Internal or
Public data, but Confidential data must not be accessed over public Wi-Fi
even with the VPN enabled, out of an abundance of caution. Home network
routers used to access Acme systems should have their default
administrator password changed and WPA2 or WPA3 encryption enabled.
