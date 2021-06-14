#!/usr/bin/python

# Threaded version for Invoke-EnumerateAzureSubDomains.ps1
# Originally written in Powershell by Karl Fosaaen (@kfosaaen)
# https://github.com/NetSPI/MicroBurst/blob/master/Misc/Invoke-EnumerateAzureSubDomains.ps1

# Ported into Python by Ben Jensen

import socket
import os
import argparse
import time
import threading
import asyncio
from concurrent import futures

try:
    import dns.resolver
    from tabulate import tabulate # for printing a pretty table
except ModuleNotFoundError:
    print('Use `pip install -r requirements.txt` to install the required modules to use this script')
    exit()

# returns IP if exists, returns '' if not
def socketResolveDnsName(name): 
    try:
        ip = socket.gethostbyname(name)
        if verbose:
            print(f'VERBOSE: Found {name}')
        return ip
    except:
        return ''

def resolveDnsName(name):
    try:
        answer = dns.resolver.resolve(name)
        return answer[0].address
    except:
        return ''

# saves the domain to our temp list if it exists
def checkDns(name):
    # This oneliner removes the lowest subdomain
    # e.g. "test.blob.core.windows.net" becomes "blob.core.windows.net"
    domain = '.'.join(name.split('.')[1:])
    if resolveDnsName(name):
        temp.append((name, subLookup[domain]))

# Function for threading chunks of the domainNames list
def accumulateDnsHits(chunk):
    global iterations
    for domain in chunk:
        iterations += 1
        checkDns(domain)

def progressBar():
    width = os.get_terminal_size().columns
    while iterations<numDomains:
        progressBarWidth = width-7-2*len(str(numDomains))
        print(f'[%s] [%s]'%
              (('o'*int(progressBarWidth*iterations/numDomains))
              .ljust(progressBarWidth),
               f'{iterations}/{numDomains}'.rjust(1+2*len(str(numDomains)))),
              end='\r')
    print(' '*width, end='')
    return

# Start the asynchronous tasks
async def asyncResolveDnsName(name): 
    try:
        ip = dns.resolver.resolve(name)[0].address
        if verbose:
            print(f'VERBOSE: Found {name}')
        return name
    except:
        return ''

#Asyncio library helpers
async def asyncResolveChunk(start,stop):
    global iterations
    chunk = []
    for index in range(start,stop):
        iterations += 1
        name = await asyncResolveDnsName(domainNames[index])
        if name:
            chunk.append(name)
    return chunk

async def main():
    calls = []
    for t in range(numThreads):
        start = int(numDomains * t / numThreads)
        stop = int(numDomains * (t+1) / numThreads)
        calls.append(asyncResolveChunk(start,stop))
    return await asyncio.gather(*calls)

##async def main():
##    calls=[]
##    for domain in domainNames:
##        calls.append(asyncResolveDnsName(domain))
##    return await asyncio.gather(*calls)

#Using futures
def processChunk(start,stop):
    global iterations
    output = []
    for index in range(start,stop):
        iterations+=1
        if resolveDnsName(domainNames[index]):
            output.append(domainNames[index])
    return output


if __name__=='__main__':
    startTime = time.perf_counter()

    parser = argparse.ArgumentParser(description='The function will check for valid Azure subdomains, based off of a base word, via DNS.')
    baseGroup = parser.add_mutually_exclusive_group(required=True)
    baseGroup.add_argument('-b', '--base', help='The Base name to prepend/append with permutations.')
    baseGroup.add_argument('-bf', '--basefile', help='Specific file with list of base names to use.')
    parser.add_argument('-o', '--output', help='File where data will be output.')
    parser.add_argument('-p', '--permutations', help='Specific permutations file to use. Default is permutations.txt (included in this repo)')
    parser.add_argument('-t', '--threads', help='Specify the number of threads to use. Default is 5.', type=int)
    parser.add_argument('-l', '--library', help='Specify which threading library to use. Default is threading.', choices=['none','threading','asyncio','futures'], default='threading')
    parser.add_argument('-v', '--verbose', help='Verbose output flag. If enabled, the domains will be output as they are found.',
                        action='store_true')
    args = parser.parse_args()

    #track how many iterations are done for the progress bar
    iterations = 0

    # default values
    outputFilePath = ''
    permutationsFilePath = os.path.dirname(os.path.realpath(__file__)) + '\\permutations.txt'
    numThreads = 5
    verbose = False
    library = args.library

    if args.base:
        baseList = [args.base]

    if args.basefile:
        if os.path.isfile(args.basefile):
            baseFile = open(args.basefile)
            baseList = baseFile.readlines()
            baseFile.close()
        else:
            print('No base file found')
            exit()

    for i in range(len(baseList)):
        if '.' in baseList[i]:
            print(f'Invalid base parameter: {baseList[i]}. Removing periods from base.')
            baseList[i] = baseList[i].replace('.','')
        baseList[i] = baseList[i].strip()

    if args.output:
        outputFilePath = args.output

    if args.verbose:
        verbose = True

    if args.permutations:
        permutationsFilePath = args.permutations

    if args.threads:
        numThreads = args.threads

    if numThreads < 1:
        print(f'Invalid thread count: {numThreads}. Defaulting back to 5.')
        numThreads = 5 

    temp = [] # stores Subdomains and their Service as tuple pairs

    # Domain = Service dictionary for easier lookups
    subLookup = {
        'onmicrosoft.com':'Microsoft Hosted Domain',
        'scm.azurewebsites.net':'App Services - Management',
        'azurewebsites.net':'App Services',
        'p.azurewebsites.net':'App Services',
        'cloudapp.net':'App Services',
        'file.core.windows.net':'Storage Accounts - Files',
        'blob.core.windows.net':'Storage Accounts - Blobs',
        'queue.core.windows.net':'Storage Accounts - Queues',
        'table.core.windows.net':'Storage Accounts - Tables',
        'mail.protection.outlook.com':'Email',
        'sharepoint.com':'SharePoint',
        'redis.cache.windows.net':'Databases-Redis',
        'documents.azure.com':'Databases-Cosmos DB',
        'database.windows.net':'Databases-MSSQL',
        'vault.azure.net':'Key Vaults',
        'azureedge.net':'CDN',
        'search.windows.net':'Search Appliance',
        'azure-api.net':'API Services'
    }

    # Load permutation words from file
    try:
        if permutationsFilePath and os.path.isfile(permutationsFilePath):
            permutations = open(permutationsFilePath)
            permutationContent = permutations.readlines()
            permutations.close()
            # Remove whitespace characters from the word list
            permutationContent = list(map(lambda line: line.strip(), permutationContent))
        else:
            print('No permutations file found')
            exit()
    except:
        print('Error loading permutations file')
        exit()

    # List of all domain names
    domainNames = []

    # Patterns for joining the permutations with the base
    patternList = ('{word}-{base}','{base}-{word}','{word}{base}','{base}{word}')


    # Generate list of all domains that this script will check
    for base in baseList:
        for domain in subLookup.keys():
            domainNames.append(f'{base}.{domain}')
            for pattern in patternList:
                for word in permutationContent:
                    domainNames.append(pattern.format(word=word, base=base) + '.' + domain)


    numDomains = len(domainNames)

    #-------------------------
    #Threading

    threads = []

    if library=='threading':
        # Start the threads!
        for i in range(numThreads):
            start = int(numDomains*i/numThreads)
            stop = int(numDomains*(i+1)/numThreads)
            threads.append(threading.Thread(target=accumulateDnsHits, args=[domainNames[start:stop]]))
            threads[i].start()

        # The progress bar doesn't play well with other print statements
        # So it's disabled if verbose mode is active
        if not verbose:
            progressBarThread = threading.Thread(target=progressBar, args=[])
            progressBarThread.start()

        for thread in threads:
            thread.join()

        if not verbose:
            progressBarThread.join()
    #------------------------------

    #------------------------
    #Asyncio
    if library=='asyncio':
        if not verbose:
            progressBarThread = threading.Thread(target=progressBar)
            progressBarThread.start()
        loop = asyncio.get_event_loop()
        aTemp = loop.run_until_complete(main())
        aTemp = list(filter(lambda domain: domain!='', aTemp))
        for chunks in aTemp:
            for domain in chunks:
                temp.append(
                    (domain,
                    subLookup['.'.join(domain.split('.')[1:])]
                    )
                )
        progressBarThread.join()
    #------------------------

    #--------------------
    #Using Futures

    if library=='futures':
        fTemp = []
        with futures.ThreadPoolExecutor(max_workers=numThreads) as executor:
            future_dnsresolve = []
            if not verbose:
                progressBarThread = threading.Thread(target=progressBar)
                progressBarThread.start()
            for i in range(numThreads):
                start = int(numDomains * i / numThreads)
                stop = int(numDomains * (i+1) / numThreads)
                future_dnsresolve.append(executor.submit(processChunk, start, stop))
            for future in futures.as_completed(future_dnsresolve):
                fTemp = fTemp + future.result()
        if not verbose:
            progressBarThread.join()
        for domain in fTemp:
            temp.append(
                (domain,
                subLookup['.'.join(domain.split('.')[1:])]
                )
            )
    #------------------------

    #------------------------------
    #Without any threading

    if library=='none':
        if not verbose:
            progressBarThread = threading.Thread(target=progressBar)
            progressBarThread.start()
        for domain in domainNames:
            iterations+=1
            if resolveDnsName(domain):
                temp.append(
                    (domain,
                    subLookup['.'.join(domain.split('.')[1:])]
                    )
                )
        if not verbose:
            progressBarThread.join()
    #----------------------------------

    # This prints it out tabulated (pretty table) and sorted by the 2nd element (services)
    print(tabulate(sorted(temp, key=lambda s: s[1]), headers=['Subdomain','Service']))
    print('\n')

    if outputFilePath:
        try:
            outputFile = open(outputFilePath, 'a')
            for hit,_ in temp:
                outputFile.write(hit + '\n')
            outputFile.close()
        except:
            print(f'Unable to write to {outputFile}')

    print(f'Total runtime: {time.perf_counter() - startTime} seconds')