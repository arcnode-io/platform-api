# Platform API 🚢

![](https://img.shields.io/gitlab/pipeline-status/arcnode-io/platform-api?branch=main&logo=gitlab)
![](https://gitlab.com/arcnode-io/platform-api/badges/main/coverage.svg)
![](https://img.shields.io/badge/ty_checked-gray?logo=astral)
![](https://img.shields.io/badge/3.13-gray?logo=python)
![](https://img.shields.io/badge/web_framework-fastapi-27a699)

> Order intake, delivery orchestration, and versioned artifact portal



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

database artifact_s3
database platform_db
cloud ses

customer -r-> website
website -r--> orchestrator: http
orchestrator -r- platform_db: sql
orchestrator --> edp_api: http
orchestrator --> cfn 
orchestrator --> iso
orchestrator --> delivery
cfn --> artifact_s3: s3
iso --> artifact_s3: s3
apk_build -r-> artifact_s3: s3
delivery <-u-> artifact_s3: s3
delivery -l-> ses: http
ses -u-> customer: email
```
### Sequence
```plantuml
actor customer
participant website
participant orchestrator
participant cfn
participant iso
participant delivery
database platform_db
database artifact_s3
participant edp_api
participant ses
participant ems_hmi_cicd

customer -> website : submit form
website -> orchestrator : POST /submit
orchestrator --> website : 200 "form submitted"
orchestrator -> platform_db : store config
platform_db --> orchestrator : cfg_id
loop until status == complete
    orchestrator -> edp_api : GET /edp-api/jobs/{job_id}
    edp_api --> orchestrator : { status, edp_artifacts[],  flags }
end

alt cloud
    orchestrator -> cfn : compose(dtm.json)
    cfn -> artifact_s3 : put cfn.yaml
    artifact_s3 --> cfn : cfn_url
    cfn --> orchestrator : cfn_url
else onprem
    orchestrator -> iso : build(dtm.json))
    iso -> artifact_s3 : put iso.img
    artifact_s3 --> iso : iso_url
    iso --> orchestrator : iso_url
end

ems_hmi_cicd -> artifact_s3 : put apk

orchestrator -> edp_api : POST /edp-api/jobs (ConfiguratorPayload)
edp_api --> orchestrator : 202 { job_id, edp_artifact_urls[] }
orchestrator -> delivery : create({ edp_artifact_urls[], iso_url|cfn_url, apk_url })
delivery -> artifact_s3 : put manifest.json + index.html
artifact_s3 --> delivery : page_url
delivery -> ses : send email { page_url }
ses -> customer : delivery email
```
