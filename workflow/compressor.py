from workflow.llm import get_llm
from workflow.memory import load_user_profile, save_user_profile
from langchain_core.messages import HumanMessage, SystemMessage
import json

llm = get_llm()

def compress_memory(user_id: str, feedback_text: str):
    """
    LLM-based memory compression: extracts new rules/preferences from feedback.
    """
    current_profile = load_user_profile(user_id)
    
    prompt = f"""
    Current User Profile: {current_profile}
    User Feedback after ride: "{feedback_text}"
    
    Analyze the feedback and update the User Profile. 
    Focus on extracting:
    1. Performance bottleneck (e.g., "legs hurt after 40km").
    2. Preferences (e.g., "hate strong winds", "prefer bike lanes").
    3. Rules for future planning (e.g., "if wind > 15, reduce mileage").
    
    Return the UPDATED full profile as a single JSON object.
    """
    
    response = llm.invoke([SystemMessage(content="Return JSON only."), HumanMessage(content=prompt)])
    try:
        new_profile = json.loads(response.content)
        save_user_profile(user_id, new_profile)
        return new_profile
    except:
        print("Memory compression failed to parse JSON.")
        return current_profile

if __name__ == "__main__":
    test_uid = "user_001"
    feedback = "这次去妙峰山太累了，由于风太大大约5级，我最后5公里几乎推车过去的。我的膝盖也有点不舒服，看来以后不能骑坡度太大的路。"
    print("Compressing memory...")
    updated = compress_memory(test_uid, feedback)
    print(f"Updated Profile: {updated}")
