# primare
HA Custom_Integration for Primare SP(A)25 Prisma

under custom_integrations create a folder named "primare"
and put the following files there:

__init__.py
const.py
manifest.json
number.py
select.py
switch.py

in number.py, select.py and switch.py replace the IP with the IP of your Primare SP25 Prisma or SPA25 Prisma.
(SPA25_IP = "xxx.xxx.xxx.xxx" """ enter the IP of your primare device here""")

in configuration.yaml put the following:

switch:
  - platform: primare

select:
  - platform: primare

number:   
  - platform: primare

save everything an restart HA
