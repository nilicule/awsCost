from typing import Any, Dict, List, Optional
import boto3
import re
import json
import uuid
from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP
from nlp_processor import NLPProcessor

# Initialize FastMCP server
mcp = FastMCP("aws_cost")

# Default AWS profile to use if none specified
DEFAULT_AWS_PROFILE = "n2g-ynni"
AWS_REGION = "eu-west-1"
AWS_ACCOUNT_ID = ""  # Optional account ID for filtering costs

# Initialize NLP processor
nlp_processor = NLPProcessor()

# Store pending requests that need MFA tokens
pending_mfa_requests = {}

async def continue_with_mfa_token(request_id: str, mfa_token: str) -> str:
    """Continue processing a request that needed an MFA token.

    Args:
        request_id: ID of the pending request
        mfa_token: MFA token to use for authentication

    Returns:
        The result of the AWS cost query
    """
    # Retrieve the pending request
    if request_id not in pending_mfa_requests:
        return f"Error: No pending request found with ID '{request_id}'"

    request = pending_mfa_requests[request_id]

    # Check if this request actually needs an MFA token
    if not request.get('needs_mfa'):
        return f"Error: The request with ID '{request_id}' does not require an MFA token"

    # Query AWS Cost Explorer with the stored parameters and the provided MFA token
    cost_data = get_cost_and_usage(
        start_date=request['start_date'],
        end_date=request['end_date'],
        granularity='MONTHLY',
        metrics=request['metrics'],
        group_by=request['group_by'],
        account_id=request['account_id'],
        profile=request['profile'],
        request_id=request_id,
        mfa_token=mfa_token
    )

    # Check if we still need an MFA token (could happen if the token is invalid)
    if isinstance(cost_data, dict) and cost_data.get('needs_mfa'):
        profile = cost_data.get('profile', DEFAULT_AWS_PROFILE)
        return f"Invalid or expired MFA token. Please provide a valid MFA token for profile '{profile}' by calling this function again with the parameters: mfa_token='your_token' and request_id='{request_id}'."

    # Check for errors
    if 'Error' in cost_data:
        # Clean up the pending request
        del pending_mfa_requests[request_id]
        return f"Error retrieving AWS cost data: {cost_data['Error']}"

    # Process the results
    results = {
        'start_date': request['start_date'],
        'end_date': request['end_date'],
        'request_type': request.get('request_type', 'summary'),
        'group_by': request['group_by'] if request['group_by'] else ['service'],
        'results': []
    }

    # Extract and format the cost data
    if 'ResultsByTime' in cost_data:
        for time_period in cost_data['ResultsByTime']:
            period_start = time_period['TimePeriod']['Start']
            period_end = time_period['TimePeriod']['End']

            # If there are groups, process each group
            if 'Groups' in time_period:
                for group in time_period['Groups']:
                    group_key = group['Keys'][0]
                    group_metrics = group['Metrics']

                    # Get the cost value for the first metric
                    metric_name = request['metrics'][0]
                    cost_value = float(group_metrics[metric_name]['Amount'])

                    # Add to results
                    dimension = request['group_by'][0] if request['group_by'] else 'service'
                    result_item = {
                        'period_start': period_start,
                        'period_end': period_end,
                        dimension: group_key,
                        'cost': cost_value
                    }
                    results['results'].append(result_item)
            else:
                # No groups, just total
                total_metrics = time_period['Total']
                metric_name = request['metrics'][0]
                cost_value = float(total_metrics[metric_name]['Amount'])

                result_item = {
                    'period_start': period_start,
                    'period_end': period_end,
                    'cost': cost_value
                }
                results['results'].append(result_item)

    # Clean up the pending request
    del pending_mfa_requests[request_id]

    # Generate a natural language response
    return nlp_processor.generate_response_text(request['query'], results)

def get_cost_explorer_client(profile=None, request_id=None, mfa_token=None):
    """Create and return a boto3 Cost Explorer client.

    Args:
        profile: AWS profile to use. If None, uses DEFAULT_AWS_PROFILE.
        request_id: ID of the request, used for tracking MFA token requests.
        mfa_token: MFA token to use for authentication, if required.
    """
    from awsume.awsumepy import awsume

    # Use the specified profile or default to n2g-ynni
    aws_profile = profile or DEFAULT_AWS_PROFILE

    try:
        # If MFA token is provided, use it
        if mfa_token:
            session = awsume(aws_profile, '-r', region=AWS_REGION, mfa_token=mfa_token)
            return session.client('ce')
        else:
            # First attempt without MFA token
            session = awsume(aws_profile, '-r', region=AWS_REGION)
            return session.client('ce')
    except Exception as e:
        error_msg = str(e)
        # Check if MFA token is required
        if "Enter MFA token" in error_msg:
            # Instead of prompting, return a special response
            if request_id:
                # Store the request parameters for later retrieval
                pending_mfa_requests[request_id] = {
                    'profile': aws_profile,
                    'region': AWS_REGION,
                    'needs_mfa': True
                }
                return {
                    'needs_mfa': True,
                    'request_id': request_id,
                    'profile': aws_profile
                }
            else:
                # If no request_id is provided, we can't store the request
                return {
                    'needs_mfa': True,
                    'error': 'No request_id provided'
                }
        else:
            print(f"Error using awsume: {e}")
            # Fall back to default boto3 behavior (uses ~/.aws/credentials)
            return boto3.client('ce', region_name=AWS_REGION)

def get_cost_and_usage(start_date: str, end_date: str, granularity: str = 'MONTHLY', 
                       metrics: List[str] = ['UnblendedCost'], 
                       group_by: Optional[List[Dict]] = None,
                       account_id: Optional[str] = None,
                       profile: Optional[str] = None,
                       request_id: Optional[str] = None,
                       mfa_token: Optional[str] = None) -> Dict[str, Any]:
    """Query AWS Cost Explorer for cost and usage data."""
    client = get_cost_explorer_client(profile, request_id, mfa_token)

    # Check if the client is a dictionary with needs_mfa flag
    if isinstance(client, dict) and client.get('needs_mfa'):
        # Return the special response indicating MFA token is needed
        return client

    try:
        # Build the request parameters
        params = {
            'TimePeriod': {
                'Start': start_date,
                'End': end_date
            },
            'Granularity': granularity,
            'Metrics': metrics
        }

        # Add GroupBy if specified
        if group_by:
            params['GroupBy'] = group_by

        # Add account filter if specified
        account_id_to_use = account_id or AWS_ACCOUNT_ID
        if account_id_to_use:
            params['Filter'] = {
                'Dimensions': {
                    'Key': 'LINKED_ACCOUNT',
                    'Values': [account_id_to_use]
                }
            }

        # Make the API call
        response = client.get_cost_and_usage(**params)
        return response
    except Exception as e:
        print(f"Error querying AWS Cost Explorer: {e}")
        return {"Error": str(e)}

@mcp.tool()
async def get_aws_cost(query: str, mfa_token: str = None, request_id: str = None) -> str:
    """Get AWS cost information based on a natural language query.

    Args:
        query: Natural language query about AWS costs (e.g., "Show me EC2 costs for last month")
        mfa_token: MFA token to use for authentication, if required
        request_id: ID of a previous request that needed an MFA token
    """
    # Check if this is a continuation of a previous request that needed an MFA token
    if mfa_token and request_id and request_id in pending_mfa_requests:
        return await continue_with_mfa_token(request_id, mfa_token)

    # Generate a unique request ID if not provided
    if not request_id:
        request_id = str(uuid.uuid4())

    # Process the natural language query
    parsed_query = nlp_processor.process_query(query)

    # Extract AWS profile if specified in the query
    profile = parsed_query.get('profile')

    # Check if a profile is specified
    if not profile:
        return "Error: No AWS profile specified in the query. Please include a profile in your query (e.g., 'using profile my-profile')."

    # Extract time period
    start_date = parsed_query.get('start_date')
    end_date = parsed_query.get('end_date')

    # If no dates specified, default to last 30 days
    if not start_date or not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    # Extract cost metrics
    metrics = nlp_processor.extract_cost_metrics(query)

    # Prepare GroupBy parameters based on the query
    group_by = []
    for dimension in parsed_query.get('group_by', ['service']):
        if dimension == 'service':
            group_by.append({
                'Type': 'DIMENSION',
                'Key': 'SERVICE'
            })
        elif dimension == 'region':
            group_by.append({
                'Type': 'DIMENSION',
                'Key': 'REGION'
            })
        elif dimension == 'account':
            group_by.append({
                'Type': 'DIMENSION',
                'Key': 'LINKED_ACCOUNT'
            })
        elif dimension == 'tag':
            # For simplicity, we're not handling specific tags here
            pass

    # Extract account ID if specified in the query
    # Since NLPProcessor doesn't extract account_id, we'll do a simple regex search
    account_id = None
    account_id_match = re.search(r'account[:\s]+(\d+)', query, re.IGNORECASE)
    if account_id_match:
        account_id = account_id_match.group(1)
    # If not found in query, use the global AWS_ACCOUNT_ID

    # Store the query parameters in the pending_mfa_requests dictionary
    pending_mfa_requests[request_id] = {
        'query': query,
        'start_date': start_date,
        'end_date': end_date,
        'metrics': metrics,
        'group_by': group_by if group_by else None,
        'account_id': account_id,
        'profile': profile,
        'needs_mfa': False  # Will be set to True if MFA is needed
    }

    # Query AWS Cost Explorer
    cost_data = get_cost_and_usage(
        start_date=start_date,
        end_date=end_date,
        granularity='MONTHLY',
        metrics=metrics,
        group_by=group_by if group_by else None,
        account_id=account_id,
        profile=profile,
        request_id=request_id,
        mfa_token=mfa_token
    )

    # Check if MFA token is needed
    if isinstance(cost_data, dict) and cost_data.get('needs_mfa'):
        # Update the pending request to indicate MFA is needed
        pending_mfa_requests[request_id]['needs_mfa'] = True

        # Return a message to the user asking for the MFA token
        profile = cost_data.get('profile', DEFAULT_AWS_PROFILE)
        return f"MFA token required for AWS authentication with profile '{profile}'. Please provide the MFA token by calling this function again with the parameters: mfa_token='your_token' and request_id='{request_id}'."

    # Check for errors
    if 'Error' in cost_data:
        return f"Error retrieving AWS cost data: {cost_data['Error']}"

    # Process the results
    results = {
        'start_date': start_date,
        'end_date': end_date,
        'request_type': parsed_query.get('request_type', 'summary'),
        'group_by': parsed_query.get('group_by', ['service']),
        'results': []
    }

    # Extract and format the cost data
    if 'ResultsByTime' in cost_data:
        for time_period in cost_data['ResultsByTime']:
            period_start = time_period['TimePeriod']['Start']
            period_end = time_period['TimePeriod']['End']

            # If there are groups, process each group
            if 'Groups' in time_period:
                for group in time_period['Groups']:
                    group_key = group['Keys'][0]
                    group_metrics = group['Metrics']

                    # Get the cost value for the first metric
                    metric_name = metrics[0]
                    cost_value = float(group_metrics[metric_name]['Amount'])

                    # Add to results
                    dimension = parsed_query.get('group_by', ['service'])[0]
                    result_item = {
                        'period_start': period_start,
                        'period_end': period_end,
                        dimension: group_key,
                        'cost': cost_value
                    }
                    results['results'].append(result_item)
            else:
                # No groups, just total
                total_metrics = time_period['Total']
                metric_name = metrics[0]
                cost_value = float(total_metrics[metric_name]['Amount'])

                result_item = {
                    'period_start': period_start,
                    'period_end': period_end,
                    'cost': cost_value
                }
                results['results'].append(result_item)

    # Generate a natural language response
    return nlp_processor.generate_response_text(query, results)

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
