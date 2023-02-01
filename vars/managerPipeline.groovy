#!groovy

boolean jobEnabled (String jobName) {
	echo "Checking if Job $jobName exists / enabled"
	try {
		if (Jenkins.instance.getItemByFullName(jobName).isBuildable()) {
			echo "Job $jobName is enabled"
			return true
		} else {
			echo "Job $jobName is disabled, Skipping"
			return false
		}
	} catch (error) {
		echo "Error: General error |$error| while checking if job |$jobName| enabled (job does not exist)"
		return false
	}
}

def triggerJob(String jobToTrigger, def parameterList = [], boolean propagate = false, boolean wait = false) {
    if (jobEnabled(jobToTrigger)) {
        echo "Triggering '$jobToTrigger'"
        try {
            jobResults=build job: jobToTrigger,
                parameters: parameterList,
                propagate: propagate,  // if true, the triggering test will fail/pass based on the status of the triggered/downstream job/s
                wait: wait  // if true, the triggering job will not end until the triggered/downstream job/s will end
        } catch(Exception ex) {
            echo "Could not trigger jon $jobToTrigger due to"
            println(ex.toString())
        }
    }
}


def completed_stages = [:]
def (testDuration, testRunTimeout, runnerTimeout, collectLogsTimeout, resourceCleanupTimeout) = [0,0,0,0,0]

def call(Map pipelineParams) {

    def builder = getJenkinsLabels(params.backend, params.region, params.gce_datacenter, params.azure_region_name)

    pipeline {
        agent {
            label {
                label builder.label
            }
        }
        environment {
            AWS_ACCESS_KEY_ID     = credentials('qa-aws-secret-key-id')
            AWS_SECRET_ACCESS_KEY = credentials('qa-aws-secret-access-key')
            SCT_TEST_ID = UUID.randomUUID().toString()
        }
        parameters {
            string(defaultValue: "${pipelineParams.get('backup_bucket_backend', '')}",
               description: 's3|gcs|azure or empty',
               name: 'backup_bucket_backend')
            string(defaultValue: "${pipelineParams.get('backend', 'aws')}",
               description: 'aws|gce',
               name: 'backend')
            string(defaultValue: "${pipelineParams.get('region', 'eu-west-1')}",
               description: 'Supported: us-east-1 | eu-west-1 | eu-west-2 | eu-north-1 | eu-central-1 | us-west-2 | random (randomly select region)',
               name: 'region')
            string(defaultValue: "${pipelineParams.get('gce_datacenter', 'us-east1')}",
                   description: 'GCE datacenter',
                   name: 'gce_datacenter')
            string(defaultValue: "${pipelineParams.get('azure_region_name', 'eastus')}",
                   description: 'Azure location',
                   name: 'azure_region_name')
            string(defaultValue: "a",
               description: 'Availability zone',
               name: 'availability_zone')


            string(defaultValue: '', description: '', name: 'scylla_ami_id')
            string(defaultValue: "${pipelineParams.get('scylla_version', '5.1')}", description: '', name: 'scylla_version')
            // When branching to manager version branch, set scylla_version to the latest release
            string(defaultValue: '', description: '', name: 'scylla_repo')
            string(defaultValue: "${pipelineParams.get('gce_image_db', '')}",
                   description: "gce image of scylla (since scylla_version doesn't work with gce)",
                   name: 'gce_image_db')  // TODO: remove setting once hydra is able to discover scylla images in gce from scylla_version
            string(defaultValue: "${pipelineParams.get('azure_image_db', '')}",
                   description: '',
                   name: 'azure_image_db')
            string(defaultValue: "${pipelineParams.get('provision_type', 'spot')}",
                   description: 'spot|on_demand|spot_fleet',
                   name: 'provision_type')
            string(defaultValue: "${pipelineParams.get('instance_provision_fallback_on_demand', 'false')}",
                   description: 'true|false',
                   name: 'instance_provision_fallback_on_demand')

            string(defaultValue: "${pipelineParams.get('post_behavior_db_nodes', 'keep-on-failure')}",
                   description: 'keep|keep-on-failure|destroy',
                   name: 'post_behavior_db_nodes')
            string(defaultValue: "${pipelineParams.get('post_behavior_loader_nodes', 'destroy')}",
                   description: 'keep|keep-on-failure|destroy',
                   name: 'post_behavior_loader_nodes')
            string(defaultValue: "${pipelineParams.get('post_behavior_monitor_nodes', 'keep-on-failure')}",
                   description: 'keep|keep-on-failure|destroy',
                   name: 'post_behavior_monitor_nodes')

            string(defaultValue: "${pipelineParams.get('tag_ami_with_result', 'false')}",
                   description: 'true|false',
                   name: 'tag_ami_with_result')

            string(defaultValue: "${pipelineParams.get('ip_ssh_connections', 'private')}",
                   description: 'private|public|ipv6',
                   name: 'ip_ssh_connections')

            string(defaultValue: "${pipelineParams.get('scylla_mgmt_address', '')}",
                   description: 'If empty - the default manager version will be taken',
                   name: 'scylla_mgmt_address')

            string(defaultValue: "${pipelineParams.get('manager_version', 'master_latest')}",
                   description: 'master_latest|3.0|2.6',
                   name: 'manager_version')

            string(defaultValue: "${pipelineParams.get('target_manager_version', '')}",
                   description: 'master_latest|3.0|2.6',
                   name: 'target_manager_version')

            string(defaultValue: "${pipelineParams.get('scylla_mgmt_agent_address', '')}",
                   description: 'manager agent repo',
                   name: 'scylla_mgmt_agent_address')

            string(defaultValue: "${pipelineParams.get('target_scylla_mgmt_server_address', '')}",
                   description: 'Link to the repository of the manager that will be used as a target of the manager server in the manager upgrade test',
                   name: 'target_scylla_mgmt_server_address')

            string(defaultValue: "${pipelineParams.get('target_scylla_mgmt_agent_address', '')}",
                   description: 'Link to the repository of the manager that will be used as a target of the manager agents in the manager upgrade test',
                   name: 'target_scylla_mgmt_agent_address')

            string(defaultValue: "'qa@scylladb.com','mgmt@scylladb.com'",
                   description: 'email recipients of email report',
                   name: 'email_recipients')

            string(defaultValue: "${pipelineParams.get('scylla_mgmt_pkg', '')}",
                   description: 'Url to the scylla manager packages',
                   name: 'scylla_mgmt_pkg')

            string(defaultValue: "${pipelineParams.get('test_config', '')}",
                   description: 'Test configuration file',
                   name: 'test_config')

            string(defaultValue: "${pipelineParams.get('test_name', '')}",
                   description: 'Name of the test to run',
                   name: 'test_name')

            string(defaultValue: "${pipelineParams.get('downstream_jobs_to_run', '')}",
                   description: 'Comma separated list of downstream jobs to run when the job passes',
                   name: 'downstream_jobs_to_run')
        }
        options {
            timestamps()
            disableConcurrentBuilds()
            buildDiscarder(logRotator(numToKeepStr: '20'))
        }
        stages {
            stage('Checkout') {
                options {
                    timeout(time: 5, unit: 'MINUTES')
                }
                steps {
                    script {
                        completed_stages = [:]
                    }
                    dir('scylla-cluster-tests') {
                        checkout scm

                        dir("scylla-qa-internal") {
                            git(url: 'git@github.com:scylladb/scylla-qa-internal.git',
                                credentialsId:'b8a774da-0e46-4c91-9f74-09caebaea261',
                                branch: 'master')
                        }
                    }
               }
            }
            stage('Get test duration') {
                options {
                    timeout(time: 2, unit: 'MINUTES')
                }
                steps {
                    catchError(stageResult: 'FAILURE') {
                        script {
                            wrap([$class: 'BuildUser']) {
                                dir('scylla-cluster-tests') {
                                    (testDuration, testRunTimeout, runnerTimeout, collectLogsTimeout, resourceCleanupTimeout) = getJobTimeouts(params, builder.region)
                                }
                            }
                        }
                    }
                }
            }
            stage('Running Downstream Jobs') {  // Specifically placed after test stage, since downstream jobs should still be triggered when stages like collect logs fail.
                options {
                    timeout(time: 5, unit: 'MINUTES')
                }
                steps {
                    script {
                        if (currentBuild.currentResult == 'SUCCESS') {
                            jobNamesToTrigger = params.downstream_jobs_to_run.split(',')
                            currentJobDirectoryPath = JOB_NAME.substring(0, JOB_NAME.lastIndexOf('/'))
                            for (downstreamJobName in jobNamesToTrigger) {
                                fullJobPath = currentJobDirectoryPath + '/' + downstreamJobName.trim()
                                def repoParams = []
                                if (downstreamJobName.contains("upgrade")) {
                                    repoParams = [
                                        [$class: 'StringParameterValue', name: 'target_scylla_mgmt_server_address', value: params.scylla_mgmt_address],
                                        [$class: 'StringParameterValue', name: 'target_scylla_mgmt_agent_address', value: params.scylla_mgmt_agent_address],
                                        [$class: 'StringParameterValue', name: 'TARGET_MANAGER_VERSION', value: params.manager_version]
                                    ]
                                } else {
                                    repoParams = [
                                        [$class: 'StringParameterValue', name: 'scylla_mgmt_address', value: params.scylla_mgmt_address],
                                        [$class: 'StringParameterValue', name: 'scylla_mgmt_agent_address', value: params.scylla_mgmt_agent_address],
                                        [$class: 'StringParameterValue', name: 'manager_version', value: params.manager_version]
                                    ]
                                }
                                triggerJob(fullJobPath, repoParams)
                            }
                        } else {
                            echo "Job failed. Will not run downstream jobs."
                        }
                    }
                }
            }
        }
    }
}
