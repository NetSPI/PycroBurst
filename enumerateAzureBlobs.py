#!/usr/bin/python

# Threaded version for Invoke-EnumerateAzureBlobs.ps1
# Originally written in Powershell by Karl Fosaaen (@kfosaaen)
# https://github.com/NetSPI/MicroBurst/blob/master/Misc/Invoke-EnumerateAzureBlobs.ps1
# Ported into Python by Ben Jensen

#import socket
import time
import argparse
import urllib
import xml.etree.ElementTree as ET
import os
import threading

try:
    import dns.resolver
    import requests
except ModuleNotFoundError:
    print('Use `pip install -r requirements.txt` to install the required modules to use this script')
    exit()


def resolveDnsName(name):
    try:
        #return socket.gethostbyname(name)
        return dns.resolver.resolve(name)[0].address
    except:
        return ''

def writeToOutput(data, outputFile):
    try:
        fileObject = open(outputFile, 'a')
        fileObject.write(data + '\n')
        fileObject.close()
    except:
        print(f'Error writing to file: {outputFile}')

def checkDnsAndAdd(name):
    if resolveDnsName(name):
        print(f'Found Storage Account - {name}')
        runningList.append(name)
        if outputFile:
            writeToOutput(name, outputFile)

def chooseFromBing(bingList):
    output = []
    choiceList = []
    for index, choiceHost in enumerate(bingList):
        print(f'{index}: {choiceHost}')
        choiceList.append(choiceHost)
    print() # new line for readability
    print('Choose any numbers from above, then press enter again.')
    print('Note: you can select multiple numbers at a time using combinations')
    print('of comma separated values and ranges, e.g. 1,3-5,10-30,35')
    choiceResponse = 'temp'
    while choiceResponse:
        choiceResponse = input('> ')
        try:
            for whiteSpace in ' \t\r\n':
                choiceResponse = choiceResponse.replace(whiteSpace, '')
            for choiceNumber in choiceResponse.split(','):
                if choiceNumber.count('-') == 1:
                    choiceRange = choiceNumber.split('-')
                    for i in range(int(choiceRange[0]), int(choiceRange[1])+1):
                        output.append(choiceList[i])
                else:
                    output.append(choiceList[int(choiceNumber)])
        except:
            if choiceResponse:
                print('Invalid input. Try again.')
            else:
                continue
    return output

def processDnsChunk(start,stop):
    for i in range(start,stop):
        lookup = lookupList[i]
        checkDnsAndAdd(lookup)

def processContainerChunk(start, stop):
    for i in range(start,stop):
        dirGuess = dirList[i]
        uriGuess = f'https://{dirGuess}?restype=container'
        try:
            guessRequest = requests.get(uriGuess)
            if guessRequest.status_code == 200:
                uriList = f'https://{dirGuess}?restype=container&comp=list'
                fileListRequest = requests.get(uriList)
                fileListXML = ET.fromstring(fileListRequest.text)
                if len(fileListXML[0]) > 0:
                    for blob in fileListXML[0]:
                        foundURL = blob.find('Name').text
                        print(f'Public File Available: https://{dirGuess}/{foundURL}')
                        if outputFile:
                            writeToOutput(foundURL, outputFile)
                else:
                    print(f'Empty Public Container Available: {uriList}')
                    if outputFile:
                        writeToOutput(uriList, outputFile)
        except:
            continue

if __name__ == '__main__':
    startTime = time.perf_counter()

    parser = argparse.ArgumentParser(description='''The function will check for valid .blob.core.windows.net host names via DNS. 
                If a BingAPIKey is supplied, a Bing search will be made for the base word under the .blob.core.windows.net site.
                After completing storage account enumeration, the function then checks for valid containers via the Azure REST API methods.
                    If a valid container has public files, the function will list them out.''')

    parser.add_argument('-b', '--base',
                        help='The Base name to prepend/append with permutations.') 

    parser.add_argument('-p', '--permutations',
                        help='Specific permutations file to use. Default is permutations.txt (included in this repo)')

    parser.add_argument('-f', '--folders',
                        help='Specific folders file to use. Default is permutations.txt (included in this repo)')

    parser.add_argument('-o', '--output',
                        help='The file to write out your results to')

    parser.add_argument('-bk', '--bingkey',
                        help='The Bing API Key to use for base name searches.')

    parser.add_argument('-t', '--threads',
                        help='Specify the number of threads to use. Default is 5.',
                        type=int, default=5)

    args = parser.parse_args()

    base = args.base
    numThreads = args.threads

    scriptDirectory = os.path.dirname(os.path.realpath(__file__))

    if args.permutations:
        permutationsFilePath = args.permutations
    else:
        permutationsFilePath = scriptDirectory + '\\permutations.txt'

    if args.folders:
        folderFilePath = args.folders
    else:
        folderFilePath = scriptDirectory + '\\permutations.txt'

    outputFile = args.output
    bingAPIKey = args.bingkey

    domain = '.blob.core.windows.net'
    runningList = []
    folderList = []
    bingList = set() #Using sets to prevent duplicates
    bingContainers = set()

    if permutationsFilePath and os.path.isfile(permutationsFilePath):
        permutations = open(permutationsFilePath)
        permutationContent = list(map(lambda line: line.strip(), permutations.readlines()))
        permutations.close()
    else:
        print('No permutations file found')
        exit()
    
    lookupList = []
    if base:
        lookup = (base+domain).lower()
        lookupList.append(lookup)
        for pattern in ['{base}{word}','{word}{base}']:
            for word in permutationContent:
                lookup = (pattern.format(word=word, base=base) + domain).lower()
                lookupList.append(lookup)
    else:
        for word in permutationContent:
            lookup = (word + domain).lower()
            lookupList.append(lookup)
    
    #Thread the DNS lookups and filter them into the runningList
    dnsThreads = []
    for i in range(numThreads):
        start = int( len(lookupList) * i / numThreads )
        stop = int( len(lookupList) * (i+1) / numThreads )
        dnsThreads.append(threading.Thread(target=processDnsChunk, args=(start,stop)))
        dnsThreads[i].start()
    for thread in dnsThreads:
        thread.join()

    if bingAPIKey and base:
        bingQuery = urllib.parse.quote('site:blob.core.windows.net '+base)
        try: 
            response = requests.get(f'https://api.bing.microsoft.com/v7.0/search?q={bingQuery}&count=50',
                                    headers={'Ocp-Apim-Subscription-Key': bingAPIKey})
            response.raise_for_status()
            webSearch = response.json()
        except:
            print('Error getting Bing API response')

        if 'webPages' in webSearch:
            for searchResults in webSearch['webPages']['value']:
                urlSplit = urllib.parse.urlsplit(searchResults['url'])
                bingList.add(urlSplit.netloc) # host name of URL
                bingContainers.add(urlSplit.path.split('/')[1]) # first entry in path
            runningList += chooseFromBing(bingList)
            for folderName in bingContainers:
                folderList.append(folderName)
        else:
            print('No results from Bing search')

    folderFile = open(folderFilePath)
    folderContent = folderFile.readlines()
    folderFile.close()
    for folderName in folderContent:
        folderList.append(folderName.strip())

    dirList = []
    for subDomain in runningList:
        for folderName in folderList:
            dirGuess = f'{subDomain}/{folderName}'.lower()
            dirList.append(dirGuess)
    
    #Thread the folder check on the storage accounts found
    containerThreads = []
    for i in range(numThreads):
        start = int(len(dirList) * i / numThreads)
        stop = int(len(dirList) * (i+1) / numThreads)
        containerThreads.append(threading.Thread(target=processContainerChunk, args=(start,stop)))
        containerThreads[i].start()
    for thread in containerThreads:
        thread.join()
    print()
    print(f'Time taken: {time.perf_counter() - startTime}')