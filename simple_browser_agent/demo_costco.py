"""
Costco Shopping Agent Demo - Browser Agent with LangGraph

This demo shows the LangGraph-based browser agent shopping at Costco.com.
Create a .env file with your Azure OpenAI credentials before running.

Task: Find and report the price of a specific product at Costco.
"""
import asyncio
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

from agent import LangGraphBrowserAgent

# Load environment variables from .env file
# Look for .env in project root (parent directory)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)


async def main():
    """Run Costco shopping demo with Azure OpenAI"""
    
    # Validate environment variables are set
    # (Agent will do this too, but check early for better error messages)
    required_vars = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY"
    ]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Please create a .env file with your Azure OpenAI credentials.\n"
            "See env.example for a template."
        )
    
    # Get configuration for display purposes only
    deployment_name = os.getenv(
        "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4o-mini"
    )
    
    # ============================================================
    # TASK - Grocery shopping with delivery
    # ============================================================
    
    task = f"""Complete a Costco grocery shopping order with the \
following items:

SHOPPING LIST:
1. Paper towels


STEPS TO COMPLETE:
1. For each item in the shopping list:
   - Find the search box and type the item name
   - Press Enter or click the search button to search
   - Extract the list of products from the search results (use extract tool)
   - Display the product options to the user (use ask_user tool)
   - Ask the user: "Here are the search results for [item name]: \
[list the products with their index numbers]. Which product would you \
like to add to cart? (Enter the index number)"
   - Wait for the user's response
   - Click on the product the user selected
   - Click "Add to Cart" button to add it to cart
   - Navigate back to search for the next item (use browser back \
or go to homepage)

2. After adding all items in the SHOPPING LIST:
   - Go to cart (click cart icon or navigate to cart page)
   - Verify all items are in the cart
   - Proceed to checkout by clicking the checkout button
   
3. If a sign-in page appears or sign-in is required:
   -Ask the user: "Sign-in is required to proceed with checkout. \
Please provide your Costco username/email:"
   - Wait for the user's response
   - Ask the user: "Please provide your Costco password:"
   - Wait for the user's response
   - Enter the provided username and password in the sign-in form
   - Click the sign-in/login button
   
4. If there's no shipping address
   - Ask the user: "Please provide your delivery address \
(e.g., 123 Main St, City, State ZIP):"
   - Wait for the user's response and use the provided address
   - Ask the user: "Please provide the recipient name:"
   - Wait for the user's response and use the provided name
   - Enter the delivery address and recipient name that the user provided

"""
    
    # ============================================================
    # AGENT SETUP
    # ============================================================
    
    print("\n" + "="*70)
    print("COSTCO SHOPPING AGENT DEMO (LangGraph)")
    print("="*70)
    print(f"\nTask: {task}")
    print(f"\nUsing: LangGraph + Azure OpenAI ({deployment_name})")
    print("="*70 + "\n")
    
    # Create the LangGraph agent (loads credentials from env internally)
    agent = LangGraphBrowserAgent(
        task=task,
        headless=False,  # Set to True to hide browser window
        max_steps=50  # Increased for complex shopping task
    )
    
    # ============================================================
    # RUN THE AGENT
    # ============================================================
    
    try:
        result = await agent.run()
        
        print("\n" + "="*70)
        print("SHOPPING COMPLETE!")
        print("="*70)
        print(f"\n{result}\n")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    # Run the Costco grocery shopping demo
    asyncio.run(main())
