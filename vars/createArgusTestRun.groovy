#!groovy

def call(Map params, String instanceType) {
    def test_config = groovy.json.JsonOutput.toJson(params.test_config)

    sh """#!/bin/bash
        set -xe

        echo "Creating Argus test run ..."

        export SCT_CLUSTER_BACKEND="${params.backend}"
        export SCT_CONFIG_FILES=${test_config}

        case "${params.backend}" in
            "aws")
                export SCT_INSTANCE_TYPE_DB="${instanceType}"
                ;;
            "gce")
                export SCT_GCE_INSTANCE_TYPE_DB="${instanceType}"
                ;;
            "azure")
                export SCT_AZURE_INSTANCE_TYPE_DB="${instanceType}"
                ;;
        esac


        ./docker/env/hydra.sh create-argus-test-run

        echo " Argus test run created."
    """
}
