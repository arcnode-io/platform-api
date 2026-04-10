# Platform API 🚢

![](https://img.shields.io/gitlab/pipeline-status/arcnode-io/platform-api?branch=main&logo=gitlab)
![](https://gitlab.com/arcnode-io/platform-api/badges/main/coverage.svg)
![](https://img.shields.io/badge/3.13-gray?logo=python)
![](https://img.shields.io/badge/web_framework-fastapi-27a699)

> Order intake, delivery orchestration ad versioned artifact portal



## Diagrams
### Deployment
```plantuml
actor customer
rectangle platform_api {
  rectangle orchestrator
  rectangle cfn
  rectangle iso
  rectangle delivery
}
rectangle website
rectangle edp_api

rectangle ems_hmi_cicd {
  rectangle apk_build
}

database platform_s3
database platform_db
cloud ses

customer -r- website
website -r- orchestrator
orchestrator -r- platform_db
orchestrator -- edp_api
orchestrator -- cfn
orchestrator -- iso
orchestrator -- delivery
cfn -- platform_s3
iso -- platform_s3
apk_build -r- platform_s3
delivery -u- platform_s3
delivery -l- ses
ses -u- customer
```
### Sequence
```plantuml
actor customer
participant website
participant orchestrator
participant cfn
participant iso
participant edp_api
participant delivery
database platform_db
database platform_s3
participant ses
participant ems_hmi_cicd

customer -> website : submit form
website -> orchestrator : POST /submit
orchestrator --> website : 200 "check your inbox"
orchestrator -> platform_db : store config
platform_db --> orchestrator : cfg_id
alt cloud
    orchestrator -> cfn : compose()
    cfn -> platform_s3 : put cfn.yaml
    platform_s3 --> cfn : cfn_url
    cfn --> orchestrator : cfn_url
else onprem
    orchestrator -> iso : build()
    iso -> platform_s3 : put iso.img
    platform_s3 --> iso : iso_url
    iso --> orchestrator : iso_url
end

ems_hmi_cicd -> platform_s3 : put apk

orchestrator -> edp_api : POST /generate { cfg_id, sizing_params }
edp_api --> orchestrator : { asset_urls[] }

orchestrator -> delivery : create({ asset_urls[], cfn_url, iso_url, apk_url })
delivery -> platform_s3 : put manifest.json + index.html
platform_s3 --> delivery : page_url
delivery -> ses : send email { page_url }
ses -> customer : delivery email
```
