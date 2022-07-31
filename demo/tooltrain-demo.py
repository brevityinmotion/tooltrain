import io, json, boto3, logging, base64
from botocore.exceptions import ClientError

# Define list of functionality. This section can be updated as more are added.
OPERATIONS_LIST = ['run', 'install', 'bootloader']
TOOL_LIST = ['httpx', 'gospider']

def lambda_handler(event, context):
    
    def _getParameters(paramName):
        client = boto3.client('ssm')
        response = client.get_parameter(
            Name=paramName
        )
        return response['Parameter']['Value']
        
    basePath = _getParameters('demo-bucket')
   
    # Validate parameters and values.
    # Check if queryStringParameters exist. If not, default to None to avoid errors.
    queryParameters = event.get('queryStringParameters', None)
    
    if queryParameters is None:
        return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Nothing to process. Missing parameters."})}
    
    else:
        programName = event["queryStringParameters"].get('program', None)
        operationType = event['queryStringParameters'].get('operation', None)
        toolName = event['queryStringParameters'].get('tool', None)
    
    
    if toolName is None:
        return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Missing tool name."})}
    if operationType is None:
        return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Missing operation name."})}
    if (toolName not in TOOL_LIST):
        return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Missing a valid tool name. Must be " + str(TOOL_LIST) + "."})}
    if (operationType not in OPERATIONS_LIST):
        return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Missing a valid operation value. Must be " + str(OPERATIONS_LIST) + "."})}
    if operationType == 'run':
        if programName is None:
            return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Missing program name is required for the run operation."})}
    if operationType == 'bootloader':
        if programName is None:
            return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Missing program name."})}
        if toolName is None:
            return {"isBase64Encoded":False,"statusCode":400,"body":json.dumps({"error":"Missing tool name."})}
    
    status = generateScript(programName, operationType, toolName, basePath)
    
    if (status is None):
        htmloutput = 'Error in processing.'
    else:
        htmloutput = '<a href="' + status + '">Download the ' + toolName + ' ' + operationType + ' script.</a>'
    
    response = {
        "statusCode": 200,
        "body": htmloutput,
        "headers": {
            'Content-Type': 'text/html',
        }
    }
    return response

# Retrieve an AWS Secrets Manager secret
def get_secret(secret_name, region_name):

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    # In this sample we only handle the specific exceptions for the 'GetSecretValue' API.
    # See https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
    # We rethrow the exception by default.

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            # An error occurred on the server side.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            # You provided an invalid value for a parameter.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            # You provided a parameter value that is not valid for the current state of the resource.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            # We can't find the resource that you asked for.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
    else:
        # Decrypts secret using the associated KMS CMK.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
            return secret

        else:
            decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])
            return decoded_binary_secret

# upload memory buffers to AWS S3 bucket
def upload_object(file_name, bucket, object_name=None):
    
    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = file_name

    # Upload the file
    s3_client = boto3.client('s3')
    try:
        response = s3_client.put_object(Body=file_name, Bucket=bucket, Key=object_name)
    except ClientError as e:
        logging.error(e)
        return 'Failed to upload file.'
    
    # Generate a pre-signed URL
    try:
        url = s3_client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket':bucket, 'Key':object_name},
            ExpiresIn=1000
        )
        return url
    
    except ClientError:
        return 'URL generation failed.'

def generateScript(programName,operationType,toolName,basePath):
    
    status = 'Nothing generated'
    
    if (operationType == 'run'):
        status = generateRunScript(programName, toolName, basePath)
    
    if (operationType == 'install'):
        status = generateInstallScript(toolName, basePath)
        
    if (operationType == 'bootloader'):
        runStatus = generateRunScript(programName, toolName, basePath)
        installStatus = generateInstallScript(toolName, basePath)
        status = generateBootloaderScript(programName, toolName, basePath)
    
    return status

def generateRunScript(programName, toolName, basePath):
    
    operationType = 'run'
    fileBuffer = io.StringIO()
    fileContents = ''
    
    if (toolName == 'gospider'):
        fileContents = f"""#!/bin/bash
# Run custom goSpider script
export HACK=/root
export PATH=/root/go/bin:$PATH
mkdir $HACK/security/refined/{programName}
mkdir $HACK/security/refined/{programName}/crawl
gospider -S $HACK/security/inputs/{programName}/{programName}-urls-base.txt -o $HACK/security/raw/{programName}/crawl -u web -t 1 -c 5 -d 1 --js --sitemap --robots --other-source --include-subs --include-other-source
cd $HACK/security/raw/{programName}/
# Pipes everything within the crawl directory, anew will unique them, and then they are written to a consolidated file.
# -urls-min.txt - The regex attempts to only retrieve the base urls, stopping at any parameters.
# -urls-max.txt - The regex includes all of the full urls but uniques any duplicates.
cat crawl/* | grep -Eo '(http|https)://[^/?:&"]+' | anew > $HACK/security/refined/{programName}/{programName}-urls-min.txt
sleep 20
cat crawl/* | grep -Eo '(http|https):\/\/[^]*]+' | anew > $HACK/security/refined/{programName}/{programName}-urls-max.txt
sleep 20
# This section will create an individual url listing for each domain passed in to crawl. I have no idea what that last bracket of symbols is doing, but it somehow writes in the filename.
FILES=$HACK/security/raw/{programName}/crawl/*
for f in $FILES
do
    cat $f | grep -Eo '(http|https)://[^/?:&"]+' | anew > $HACK/security/refined/{programName}/crawl/urls-simple-${{f##*/}}.txt
done
sleep 10                                                                      
sh $HACK/security/run/{programName}/sync-{programName}.sh
wait
sh $HACK/security/run/{programName}/stepfunctions-{programName}.sh"""

    if (toolName == 'httpx'):
        inputPath = 'urls.txt'
        fileContents = f"""#!/bin/bash
# Run custom httpx script
export HACK=/root
export PATH=/root/go/bin:$PATH
mkdir $HACK/security/raw/{programName}/responses
mkdir $HACK/security/raw/{programName}/httpx
mkdir $HACK/security/presentation
mkdir $HACK/security/presentation/httpx-json
export HTTPXINPUTPATH={inputPath}
if [ -f "$HTTPXINPUTPATH" ]; then
    httpx -json -o $HOME/security/presentation/httpx-json/{programName}-httpx.json -l {inputPath} -status-code -title -location -content-type -web-server -no-color -tls-probe -x GET -ip -cname -cdn -content-length -sr -srd $HOME/security/raw/{programName}/responses -timeout 1
fi
sleep 10
# Remove .txt from all of the files
echo 'Completed crawl'
cd $HACK/security/raw/{programName}/responses/
for f in *.txt; do mv -- "$f" "${{f%.txt}}"; done
sleep 10
cd $HACK/security/raw/{programName}/
sleep 10
sh $HACK/security/run/{programName}/sync-{programName}.sh
wait
sh $HACK/security/run/{programName}/stepfunctions-{programName}.sh"""

    # Upload file to S3
    fileBuffer.write(fileContents)
    objectBuffer = io.BytesIO(fileBuffer.getvalue().encode())
    object_name = operationType + '-' + toolName + '.sh'
    object_path = operationType + '/' + programName + '/' + object_name
    status = upload_object(objectBuffer,basePath,object_path)
    fileBuffer.close()
    objectBuffer.close()
    return status
    
def generateInstallScript(toolName, basePath):
    
    operationType = 'install'
    fileBuffer = io.StringIO()
    fileContents = ''
    
    if (toolName == 'gospider'):
    
        fileBuffer = io.StringIO()
        fileContents = f"""#!/bin/bash
# Create directory structure
export HOME=/root
mkdir $HOME/security
mkdir $HOME/security/tools
mkdir $HOME/security/tools/amass
mkdir $HOME/security/tools/amass/db
mkdir $HOME/security/tools/hakrawler
mkdir $HOME/security/tools/httpx
mkdir $HOME/security/raw
mkdir $HOME/security/refined
mkdir $HOME/security/curated
mkdir $HOME/security/scope
mkdir $HOME/security/install
mkdir $HOME/security/config
mkdir $HOME/security/run
mkdir $HOME/security/inputs
# Update apt repositories to avoid software installation issues
apt-get update
# Ensure OS and packages are fully upgraded
#apt-get -y upgrade
# Install Git
apt-get install -y git # May already be installed
# Install Python and Pip
apt-get install -y python3 # Likely is already installed
apt-get install -y python3-pip
# Install Golang via cli
apt-get install -y golang
echo 'export GOROOT=/usr/lib/go' >> ~/.bashrc
echo 'export GOPATH=$HOME/go' >> ~/.bashrc
echo 'export PATH=$GOPATH/bin:$GOROOT/bin:$PATH' >> ~/.bashrc
#source ~/.bashrc
    
# Install aws cli
apt-get install -y awscli
# Install go tools
go get -u github.com/tomnomnom/anew
go get -u github.com/jaeles-project/gospider"""
    
    fileBuffer.write(fileContents)
    objectBuffer = io.BytesIO(fileBuffer.getvalue().encode())

    # Upload file to S3
    object_name = operationType + '-' + toolName + '.sh'
    object_path = operationType + '/' + object_name
    status = upload_object(objectBuffer,basePath,object_path)
    fileBuffer.close()
    objectBuffer.close()
    return status
        
def generateBootloaderScript(programName, toolName, basePath):
    
    operationType = 'bootloader'
    fileBuffer = io.StringIO()
    fileContents = ''
    
    # Load AWS access keys for s3 synchronization
    secretName = 'brevity-straylight'
    regionName = 'us-east-1'
    secretRetrieved = get_secret(secretName,regionName)
    secretjson = json.loads(secretRetrieved)
    awsAccessKeyId = secretjson['accesskey']
    awsSecretKey = secretjson['secretaccesskey']
    fileContents = f"""#cloud-config
packages:
    - awscli
runcmd:
    - export HACK=/root
    - mkdir $HACK/security
    - mkdir $HACK/security/install
    - mkdir $HACK/security/run/{programName}
    - export AWS_ACCESS_KEY_ID={awsAccessKeyId}
    - export AWS_SECRET_ACCESS_KEY={awsSecretKey}
    - export AWS_DEFAULT_REGION={regionName}
    - aws s3 sync s3://{basePath}/config/ $HACK/security/config/
    - wait
    - aws s3 sync s3://{basePath}/run/{programName}/ $HACK/security/run/{programName}/
    - wait
    - sh $HACK/security/install/install-{toolName}.sh
    - wait
    - sh $HACK/security/run/{programName}/{toolName}-{programName}.sh
    - wait
    - aws s3 sync s3://{basePath}/run/{programName}/ $HACK/security/run/
    - wait
    - shutdown now"""

    # Upload file to S3
    fileBuffer.write(fileContents)
    objectBuffer = io.BytesIO(fileBuffer.getvalue().encode())
    object_name = operationType + '-' + toolName + '.sh'
    object_path = operationType + '/' + programName + '/' + object_name
    status = upload_object(objectBuffer,basePath,object_path)
    fileBuffer.close()
    objectBuffer.close()
    return status
