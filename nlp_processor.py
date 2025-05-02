import re
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional


class NLPProcessor:
    """
    Local Natural Language Processing module for AWS cost queries
    """

    def __init__(self):
        """Initialize the NLP processor with service taxonomy"""
        # Load the cost taxonomy for AWS services
        self.taxonomy = self._load_taxonomy()
        self.region_mapping = self._load_region_mapping()

    def _load_taxonomy(self) -> Dict[str, Any]:
        """Load AWS services taxonomy for better mapping of queries"""
        return {
            "compute": ["ec2", "lambda", "elastic compute", "fargate", "batch", "lightsail"],
            "storage": ["s3", "ebs", "glacier", "storage gateway", "backup"],
            "database": ["rds", "dynamodb", "aurora", "elasticache", "neptune", "timestream"],
            "networking": ["vpc", "route53", "cloudfront", "api gateway", "direct connect"],
            "analytics": ["athena", "emr", "kinesis", "glue", "quicksight"],
            "machine_learning": ["sagemaker", "rekognition", "comprehend", "textract", "forecast"],
            "security": ["iam", "kms", "waf", "shield", "cognito"],
            "management_tools": ["cloudwatch", "cloudtrail", "config", "organizations"]
        }

    def _load_region_mapping(self) -> Dict[str, str]:
        """Load AWS region mapping from common names to region codes"""
        return {
            "us east": "us-east-1",
            "us east 2": "us-east-2",
            "us west": "us-west-2",
            "us west 1": "us-west-1",
            "europe": "eu-west-1",
            "eu": "eu-west-1",
            "london": "eu-west-2",
            "paris": "eu-west-3",
            "frankfurt": "eu-central-1",
            "asia": "ap-southeast-1",
            "singapore": "ap-southeast-1",
            "tokyo": "ap-northeast-1",
            "sydney": "ap-southeast-2",
            "mumbai": "ap-south-1",
            "south america": "sa-east-1",
            "brazil": "sa-east-1"
        }

    def process_query(self, query: str) -> Dict[str, Any]:
        """
        Process a natural language query about AWS costs

        Args:
            query: The natural language query string

        Returns:
            Dict containing the parsed parameters for the cost query
        """
        # Default to basic keyword parser
        return self._parse_query(query.lower())

    def _parse_query(self, query: str) -> Dict[str, Any]:
        """
        Parse the query using keyword matching and pattern recognition

        Args:
            query: The lowercase natural language query string

        Returns:
            Dict containing the parsed parameters for the cost query
        """
        result = {
            "services": [],
            "start_date": None,
            "end_date": None,
            "regions": [],
            "group_by": [],
            "request_type": "summary",
            "profile": None  # AWS profile to use
        }

        # Extract services
        for category, keywords in self.taxonomy.items():
            for keyword in keywords:
                if keyword in query:
                    result["services"].append(keyword)

        # Extract AWS service names directly
        aws_service_regex = r'\b(ec2|s3|rds|lambda|dynamodb|sqs|sns|cloudfront|route53|cloudwatch|iam|kms)\b'
        direct_services = re.findall(aws_service_regex, query)
        for service in direct_services:
            if service not in result["services"]:
                result["services"].append(service)

        # Extract time references
        self._extract_time_periods(query, result)

        # Extract regions
        self._extract_regions(query, result)

        # Extract grouping dimensions
        self._extract_grouping(query, result)

        # Extract request type
        self._extract_request_type(query, result)

        # Extract AWS profile
        self._extract_profile(query, result)

        return result

    def _extract_time_periods(self, query: str, result: Dict[str, Any]) -> None:
        """Extract time periods from the query"""
        # Check for specific time period keywords
        time_keywords = {
            "today": {"days": 0},
            "yesterday": {"days": 1},
            "this week": {"days": 7},
            "last week": {"days": 7},
            "this month": {"days": 30},
            "last month": {"days": 30},
            "this quarter": {"days": 90},
            "last quarter": {"days": 90},
            "this year": {"days": 365},
            "last year": {"days": 365}
        }

        now = datetime.now()

        for time_ref, duration in time_keywords.items():
            if time_ref in query:
                days = duration["days"]
                if time_ref.startswith("last"):
                    # "Last week" means the 7 days before this week
                    end_date = now - timedelta(days=days)
                    start_date = end_date - timedelta(days=days)
                else:
                    # "This week" means from 7 days ago until now
                    end_date = now
                    start_date = now - timedelta(days=days)

                result["start_date"] = start_date.strftime('%Y-%m-%d')
                result["end_date"] = end_date.strftime('%Y-%m-%d')
                return

        # Look for specific date patterns (YYYY-MM-DD or MM/DD/YYYY)
        date_patterns = [
            r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
            r'(\d{1,2}/\d{1,2}/\d{4})'  # MM/DD/YYYY
        ]

        dates = []
        for pattern in date_patterns:
            dates.extend(re.findall(pattern, query))

        if len(dates) >= 2:
            # If we found at least two dates, use them as start and end
            result["start_date"] = dates[0]
            result["end_date"] = dates[1]
        elif len(dates) == 1:
            # If we found just one date, use it as start and today as end
            result["start_date"] = dates[0]
            result["end_date"] = now.strftime('%Y-%m-%d')
        else:
            # Default to last 30 days
            result["start_date"] = (now - timedelta(days=30)).strftime('%Y-%m-%d')
            result["end_date"] = now.strftime('%Y-%m-%d')

    def _extract_regions(self, query: str, result: Dict[str, Any]) -> None:
        """Extract AWS regions from the query"""
        # Check for direct region codes
        region_regex = r'\b(us-east-1|us-east-2|us-west-1|us-west-2|eu-west-1|eu-west-2|eu-central-1|ap-southeast-1|ap-southeast-2|ap-northeast-1|sa-east-1)\b'
        direct_regions = re.findall(region_regex, query)

        # Add any direct region matches
        result["regions"].extend(direct_regions)

        # Check for common region names
        for region_name, region_code in self.region_mapping.items():
            if region_name in query and region_code not in result["regions"]:
                result["regions"].append(region_code)

    def _extract_grouping(self, query: str, result: Dict[str, Any]) -> None:
        """Extract grouping dimensions from the query"""
        grouping_keywords = {
            "service": ["by service", "per service", "each service", "across services"],
            "region": ["by region", "per region", "each region", "across regions"],
            "account": ["by account", "per account", "each account", "across accounts"],
            "instance_type": ["by instance type", "per instance", "instance types"],
            "resource": ["by resource", "per resource", "each resource"],
            "tag": ["by tag", "per tag", "each tag"]
        }

        for group_by, keywords in grouping_keywords.items():
            for keyword in keywords:
                if keyword in query and group_by not in result["group_by"]:
                    result["group_by"].append(group_by)

        # If no grouping specified, default to service
        if not result["group_by"]:
            result["group_by"].append("service")

    def _extract_request_type(self, query: str, result: Dict[str, Any]) -> None:
        """Extract the type of cost request from the query"""
        request_types = {
            "summary": ["summary", "overview", "total", "how much"],
            "detailed": ["detailed", "breakdown", "details", "itemized"],
            "comparison": ["compare", "comparison", "versus", "vs", "difference"],
            "trend": ["trend", "over time", "historical", "month over month", "year over year"],
            "forecast": ["forecast", "predict", "estimation", "projected", "future"],
            "optimization": ["optimize", "optimization", "savings", "reduce costs", "cost cutting"]
        }

        for req_type, keywords in request_types.items():
            for keyword in keywords:
                if keyword in query:
                    result["request_type"] = req_type
                    return

    def _extract_profile(self, query: str, result: Dict[str, Any]) -> None:
        """Extract AWS profile from the query"""
        # Look for profile keywords
        profile_keywords = ["profile", "aws profile", "using profile", "with profile"]

        for keyword in profile_keywords:
            if keyword in query:
                # Look for profile name after the keyword
                pattern = f"{keyword}\\s+([\\w-]+)"
                match = re.search(pattern, query)
                if match:
                    result["profile"] = match.group(1)
                    return

        # Also check for direct profile mentions
        profile_pattern = r'\b(profile\s+[\w-]+|[\w-]+\s+profile)\b'
        match = re.search(profile_pattern, query)
        if match:
            # Extract the profile name
            profile_text = match.group(1)
            if "profile " in profile_text:
                result["profile"] = profile_text.replace("profile ", "")
            else:
                result["profile"] = profile_text.replace(" profile", "")

    def extract_cost_metrics(self, query: str) -> List[str]:
        """
        Extract cost metrics from the query

        Args:
            query: The query string

        Returns:
            List of cost metrics
        """
        metrics = ["UnblendedCost"]  # Default metric

        metric_keywords = {
            "BlendedCost": ["blended", "blended cost"],
            "UnblendedCost": ["unblended", "unblended cost"],
            "AmortizedCost": ["amortized", "amortized cost"],
            "NetAmortizedCost": ["net amortized", "net amortized cost"],
            "NetUnblendedCost": ["net unblended", "net unblended cost"],
            "UsageQuantity": ["usage", "quantity", "usage quantity"]
        }

        for metric, keywords in metric_keywords.items():
            for keyword in keywords:
                if keyword in query:
                    # Replace default with the specific metric
                    if metrics == ["UnblendedCost"]:
                        metrics = [metric]
                    else:
                        metrics.append(metric)

        return metrics

    def generate_response_text(self, query: str, results: Dict[str, Any]) -> str:
        """
        Generate a natural language response to the cost query

        Args:
            query: The original query string
            results: The results from the cost query

        Returns:
            A natural language response summarizing the results
        """
        request_type = results.get("request_type", "summary")
        total_cost = sum(item.get('cost', 0) for item in results.get('results', []))

        # Extract time period
        start_date = results.get('start_date', 'the specified period')
        end_date = results.get('end_date', '')

        if start_date and end_date:
            time_period = f"from {start_date} to {end_date}"
        else:
            time_period = "for the specified period"

        # Generate appropriate response based on request type
        if request_type == "summary":
            response = f"Your total AWS cost {time_period} was ${total_cost:.2f}."

            # Add service breakdown if available
            if len(results.get('results', [])) > 1:
                response += " Here's a breakdown by service:\n"

                # Sort services by cost
                sorted_results = sorted(
                    results.get('results', []),
                    key=lambda x: x.get('cost', 0),
                    reverse=True
                )

                # Add top 5 services
                for i, item in enumerate(sorted_results[:5]):
                    service = item.get('service', 'Unknown service')
                    cost = item.get('cost', 0)
                    response += f"- {service}: ${cost:.2f}\n"

                if len(sorted_results) > 5:
                    response += f"- Others: ${sum(item.get('cost', 0) for item in sorted_results[5:]):.2f}\n"

        elif request_type == "detailed":
            response = f"Detailed cost breakdown {time_period}:\n"

            # Group by the first dimension
            dimension = next(iter(results.get('group_by', ['service'])))

            # Sort by cost
            sorted_results = sorted(
                results.get('results', []),
                key=lambda x: x.get('cost', 0),
                reverse=True
            )

            for item in sorted_results:
                dim_value = item.get(dimension, 'Unknown')
                cost = item.get('cost', 0)
                response += f"- {dim_value}: ${cost:.2f}\n"

        elif request_type == "comparison":
            response = f"Cost comparison {time_period}:\n"
            # Implementation would depend on the specific comparison requested

        elif request_type == "trend":
            response = f"Cost trend {time_period}:\n"
            # Implementation would depend on trend analysis

        elif request_type == "optimization":
            response = f"Cost optimization recommendations for your AWS usage:\n"

            # Add some generic recommendations
            response += "1. Consider using Reserved Instances for stable workloads\n"
            response += "2. Review and terminate unused resources\n"
            response += "3. Implement auto-scaling for variable workloads\n"
            response += "4. Use appropriate storage tiers (S3 lifecycle policies)\n"
            response += "5. Enable and review AWS Cost Explorer regularly\n"

        else:
            response = f"AWS cost analysis results {time_period}:\n"
            response += f"Total cost: ${total_cost:.2f}"

        return response
