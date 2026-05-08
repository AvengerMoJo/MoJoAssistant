# Experimental Components

This directory contains experimental and legacy components that are not actively used in the main MoJoAssistant application but are preserved for reference and potential future development.

## Contents

### Legacy Utilities (formerly `/utils`)
These components were part of earlier iterations of the project and represent different approaches to conversation management and agent architectures:

- **`Conversation.py`** - Early conversation management with Google Sheets integration
- **`ConversationalMemory.py`** - Basic conversational memory implementation
- **`ListSubjectDetail.py`** - Subject detail extraction utilities
- **`PlanExecutorAgent.py`** - Plan-and-execute agent implementation using LangChain
- **`ZeroShotAgent.py`** - Zero-shot agent implementation
- **`Gorilla-Local.py`** - Local Gorilla model integration
- **`Gorilla-OpenFunction.py`** - OpenFunction Gorilla integration

## Status

⚠️ **These components are experimental and not actively maintained.**

- They may have outdated dependencies
- They are not integrated with the current memory architecture
- They serve as reference implementations for alternative approaches
- Some may require additional setup or API keys to function

## Usage

These components can be used for:
- Research and experimentation with different agent architectures
- Reference implementations for specific functionality
- Prototyping new features before integration into the main system

## Migration Notes

If you want to integrate any of these components into the main application:
1. Update dependencies to match current `requirements.txt`
2. Adapt to the current memory architecture
3. Follow the established patterns in the `app/` directory
4. Add appropriate tests and documentation
