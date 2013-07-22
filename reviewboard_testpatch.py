#!/usr/bin/python
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import json
import requests
import sys
import time
import ConfigParser
import StringIO

review_url   = "https://reviews.apache.org"
review_user  = "XXXXXXXX"
review_pass  = "XXXXXXXX"

jenkins_url  = "http://jenkins.cloudstack.org"
jenkins_user = "XXXXXXXX"
jenkins_pass = "XXXXXXXX"
jenkins_job  = "cloudstack-master-with-patch"

def retrieve_object(url, params):
    r = requests.get(url, params=params)
    response = json.loads(r.text)
    if response['stat'] != "ok":
        pretty_print(response)
        raise Exception("Exception while retrieving object")
    return response

def get_repository_id_for_name(name):
    params = { 'max-results' : '1000' }
    result = retrieve_object(review_url+"/api/repositories", params)
    for repository in result['repositories']:
        if name == repository['name']:
            return repository['id']
    print "not found"
    raise Exception

def pretty_print(json_object):
    print json.dumps(json_object, sort_keys=True, indent=4, separators=(',', ': '))

def trigger_jenkins(review_id, branch, patch_file):
    r = requests.get(jenkins_url + "/job/" + jenkins_job + "/api/json")
    build_details = json.loads(r.text)
    next_build = build_details['nextBuildNumber']
    job_str = "[ " + jenkins_job + "#" + str(next_build )+ " ] "
    
    print "Triggering jenkins jobs " + jenkins_job + "#" + str(next_build) + " for review_request " + str(review_id) + " on branch " + branch
    files = {'patch.diff': ('patch.diff', patch_file)}
    r=requests.post(jenkins_url + "/job/" + jenkins_job + "/buildWithParameters", auth=(jenkins_user,jenkins_pass), files=files)
    if (r.status_code == 404):
        raise Exception("Job " + jenkins_job + " not found on " + jenkins_url)
    if (r.status_code != 200):
        raise Exception("Failed to trigger job " + jenkins_job + " on " + jenkins_url)
    while build_details['lastBuild']['number'] < next_build:
        print "Job is still pending"
        time.sleep(15) # TODO Implement some sort of timeout
        r = requests.get(jenkins_url + "/job/" + jenkins_job + "/api/json")
        build_details = json.loads(r.text)
    print "Build is running"
    r = requests.get(jenkins_url + "/job/" + jenkins_job + "/" + str(next_build) + "/api/json")
    build_status = json.loads(r.text)
    while build_status['building'] == True :
        print "Job is still building"
        time.sleep(15) # TODO Implement some sort of timeout
        r = requests.get(jenkins_url + "/job/" + jenkins_job + "/" + str(next_build) + "/api/json")
        build_status = json.loads(r.text)
    # TODO Check if this is my build by comparing review id
    print "Build completed, checking results"
    message = ""
    shipit = False
    if build_status['result'] == "SUCCESS" :
        message += "Review " + str(review_id) + " PASSED the build test\n"
        shipit = False
    else:
        message += "Review " + str(review_id) + " failed the build test : " + build_status['result'] + "\n"
        
    message += "The url of build " + build_status['fullDisplayName'] + " is : " + build_status['url']
    print "Updating review with comment : " + message
    update_review(review_id, message, shipit)
    
def update_review(reviewrequest_id, message, ship_it):
    params = { "body_top" : message, "public" : True, "ship_it" : ship_it }
    auth = (review_user,review_pass)
    r = requests.post(review_url + "/api/review-requests/" + str(reviewrequest_id) + "/reviews/", data=params, auth=auth)
    response = json.loads(r.text)
    if response['stat'] != "ok":
        pretty_print(response)
        raise Exception("Exception while retrieving object")
    pretty_print( response)
    
# check_reviews
# This function will connect to reviewboard and check if then jenkins user has posted any reviews.
# if it didn't it will trigger a jenkins build with the review id and branch for that review
def check_reviews():
    repoid = get_repository_id_for_name('cloudstack-git')

    params = { 'repository' : repoid, 'max-results': 1}
    review_requests = retrieve_object('http://reviews.apache.org/api/review-requests', params)
    
    for review_request in review_requests['review_requests']:
        print review_request['summary'] + " (" + review_request['status'] + ") "
        if not review_request['status'] == "pending":
            print "Review has state " + review_request['status'] + " skipping jenkins build"
            continue

        # TODO Add support for multiple branches, for now assume everything is for master
        #branch = review_request['branch']
        #if branch=="":
        branch = "master"
        
        # load the reviews for this request
        reviews = retrieve_object(review_url + "/api/review-requests/" + str(review_request['id']) + "/reviews/", {'max-results':1000})
        reviewed = False
        for review in reviews['reviews']:
            reviewer = review['links']['user']['title']
            if (reviewer == review_user):
                reviewed = True
                break

        if not reviewed:
            if review_request['links'].has_key('diffs'):
                diffs = retrieve_object(review_request['links']['diffs']['href'], None)
                revision = diffs['total_results']
                latest_diff = diffs['diffs'][revision-1]
                headers = { "Accept" : "text/x-patch" }
                r = requests.get(latest_diff['links']['self']['href'], headers=headers)
                buf = StringIO.StringIO(r.text)
                line = buf.readline()
                patch_file = ''
                if line.startswith('diff'):
                    # Regular patch file
                    patch_file = r.text
                elif line.startswith('From '):
                    # Git format-patch
                    while not line.startswith('diff'):
                        line = buf.readline()
                    while not (line.rstrip() == '--'):
                        patch_file += line
                        line = buf.readline()
                                    
                trigger_jenkins(review_request['id'], branch, patch_file)
            else:
                print "No diff files found for this review, nothing to test"
        else:
            print "Already reviewed"
            
try:
    config = ConfigParser.ConfigParser()
    config.readfp(open("reviewboard_testpatch.ini"))
    # TODO read and set globals
except:
    raise Exception("Unable to read configuration file")

check_reviews()

