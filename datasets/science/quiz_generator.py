"""
Quiz Generator for JHS Matatag Curriculum
Validates and generates quizzes from uploaded lesson plans
"""
import re
from typing import List, Dict, Any, Tuple
from difflib import SequenceMatcher
import random
import logging

logger = logging.getLogger(__name__)

class ScienceQuizGenerator:
    def __init__(self, grade7_questions, grade8_questions, grade9_questions=None, grade10_questions=None):
        """Initialize with science datasets"""
        grade9_questions = grade9_questions or []
        grade10_questions = grade10_questions or []
        
        self.all_questions = grade7_questions + grade8_questions + grade9_questions + grade10_questions
        self.grade7_questions = grade7_questions
        self.grade8_questions = grade8_questions
        self.grade9_questions = grade9_questions
        self.grade10_questions = grade10_questions
        
        # Create topic index
        self.topic_index = self._create_topic_index()
        
    def _create_topic_index(self) -> Dict[str, List[int]]:
        """Create index of questions by topic"""
        topic_index = {}
        for i, q in enumerate(self.all_questions):
            topic = q.get('topic', 'General')
            if topic not in topic_index:
                topic_index[topic] = []
            topic_index[topic].append(i)
        return topic_index
    
    def _get_grade_from_index(self, idx: int) -> int:
        """Determine which grade level a question belongs to based on its index"""
        grade7_end = len(self.grade7_questions)
        grade8_end = grade7_end + len(self.grade8_questions)
        grade9_end = grade8_end + len(self.grade9_questions)
        
        if idx < grade7_end:
            return 7
        elif idx < grade8_end:
            return 8
        elif idx < grade9_end:
            return 9
        else:
            return 10
    
    def extract_topics_from_lesson(self, lesson_text: str) -> Dict[str, Dict]:
        """Extract science topics from lesson plan"""
        lesson_lower = lesson_text.lower()
        topic_scores = {}
        
        # Science topic keywords based on Grade 7 curriculum
        keywords_map = {
            'Use of Models': ['model', 'diagram', 'simulation', 'representation', 'visualize', 'flowchart'],
            'Particle Model of Matter': ['particle', 'atom', 'molecule', 'kinetic', 'motion', 'arrangement'],
            'Changes of State': ['melt', 'freeze', 'boil', 'evaporate', 'condense', 'sublimate', 'state'],
            'Solutions and Solubility': ['solution', 'solute', 'solvent', 'dissolve', 'solubility', 'saturated'],
            'Scientific Investigation': ['hypothesis', 'experiment', 'variable', 'data', 'conclusion', 'method'],
            'The Compound Microscope': ['microscope', 'lens', 'objective', 'eyepiece', 'stage', 'focus'],
            'Plant and Animal Cells': ['cell', 'organelle', 'nucleus', 'cytoplasm', 'membrane', 'chloroplast'],
            'Cellular Reproduction': ['mitosis', 'meiosis', 'reproduction', 'gamete', 'zygote', 'division'],
            'Levels of Biological Organization': ['tissue', 'organ', 'system', 'organism', 'population'],
            'Trophic Levels and Energy Transfer': ['food chain', 'food web', 'producer', 'consumer', 'energy'],
            'Balanced and Unbalanced Forces': ['force', 'friction', 'gravity', 'balanced', 'unbalanced', 'net force'],
            'Speed and Velocity': ['speed', 'velocity', 'distance', 'time', 'direction', 'vector'],
            'Distance-Time Graphs': ['graph', 'slope', 'distance', 'time', 'motion', 'line'],
            'Heat and Temperature': ['heat', 'temperature', 'conduction', 'convection', 'radiation'],
            'Faults and Earthquakes': ['fault', 'earthquake', 'seismic', 'epicenter', 'magnitude'],
            'Solar Energy and Weather': ['weather', 'climate', 'monsoon', 'habagat', 'amihan', 'typhoon'],
            'Disaster Risk Reduction': ['disaster', 'risk', 'preparedness', 'evacuation', 'hazard'],
        }
        
        for topic, keywords in keywords_map.items():
            score = 0
            found_keywords = []
            for keyword in keywords:
                if keyword in lesson_lower:
                    count = lesson_lower.count(keyword)
                    score += count
                    found_keywords.append(keyword)
            
            if score > 0:
                topic_scores[topic] = {
                    'score': score,
                    'keywords': found_keywords,
                    'percentage': 0
                }
        
        # Normalize to percentages
        if topic_scores:
            total = sum(t['score'] for t in topic_scores.values())
            for topic in topic_scores:
                topic_scores[topic]['percentage'] = (topic_scores[topic]['score'] / total) * 100
        
        # Filter topics below 10% threshold
        filtered_topics = {topic: data for topic, data in topic_scores.items() if data['percentage'] >= 10}
        
        # Recalculate percentages for filtered topics to sum to 100%
        if filtered_topics:
            filtered_total = sum(t['score'] for t in filtered_topics.values())
            for topic in filtered_topics:
                filtered_topics[topic]['percentage'] = (filtered_topics[topic]['score'] / filtered_total) * 100
            topic_scores = filtered_topics
        
        return dict(sorted(topic_scores.items(), key=lambda x: x[1]['percentage'], reverse=True))
    
    def detect_quarter_from_lesson(self, lesson_text: str) -> str:
        """
        Analyze lesson text to determine which quarter the content belongs to
        based on the topics in your Grade 7 question bank
        Returns: 'First Quarter', 'Second Quarter', 'Third Quarter', 'Fourth Quarter', or None
        """
        try:
            # First try using the AI model if available
            if hasattr(self, 'model'):
                prompt = f"""Analyze this science lesson plan and determine which quarter of the Grade 7 curriculum it belongs to.
                
                The Grade 7 Science quarters cover these topics:
                
                First Quarter: Use of Models, Particle Model of Matter, Changes of State, Solutions and Solubility, Scientific Investigation
                
                Second Quarter: The Compound Microscope, Plant and Animal Cells, Cellular Reproduction, Levels of Biological Organization, Trophic Levels and Energy Transfer
                
                Third Quarter: Balanced and Unbalanced Forces, Speed and Velocity, Distance-Time Graphs, Heat and Temperature
                
                Fourth Quarter: Faults and Earthquakes, Solar Energy and Weather Patterns, Disaster Risk Reduction
                
                Lesson text:
                {lesson_text[:3000]}
                
                Based on the content, which quarter does this lesson belong to? 
                Return ONLY the quarter name exactly as written above (e.g., "First Quarter", "Second Quarter", "Third Quarter", or "Fourth Quarter").
                If you're unsure, make your best guess based on the topics present."""
                
                response = self.model.invoke(prompt)
                detected_quarter = response.content.strip()
                
                # Validate that the response matches one of our quarters
                valid_quarters = ['First Quarter', 'Second Quarter', 'Third Quarter', 'Fourth Quarter']
                
                if detected_quarter in valid_quarters:
                    return detected_quarter
            
            # Fallback to keyword matching
            return self._infer_quarter_from_keywords(lesson_text)
            
        except Exception as e:
            logger.error(f"Error detecting quarter: {e}")
            # Fallback to keyword matching
            return self._infer_quarter_from_keywords(lesson_text)

    def _infer_quarter_from_keywords(self, lesson_text: str) -> str:
        """Fallback method to infer quarter from keywords based on your question bank"""
        text_lower = lesson_text.lower()
        
        # Quarter 1 keywords (from your question bank)
        q1_keywords = [
            'model', 'particle', 'matter', 'state of matter', 'solid', 'liquid', 'gas', 
            'solution', 'solubility', 'solute', 'solvent', 'scientific investigation', 
            'hypothesis', 'experiment', 'melting', 'freezing', 'evaporation', 'condensation',
            'sublimation', 'kinetic', 'particle model'
        ]
        
        # Quarter 2 keywords
        q2_keywords = [
            'microscope', 'cell', 'organelle', 'nucleus', 'cytoplasm', 'mitochondria', 
            'chloroplast', 'cell wall', 'membrane', 'tissue', 'organ', 'system', 
            'photosynthesis', 'respiration', 'unicellular', 'multicellular', 'mitosis', 
            'meiosis', 'reproduction', 'food chain', 'food web', 'trophic', 'ecosystem',
            'gamete', 'zygote', 'chromosome', 'organism', 'population', 'community'
        ]
        
        # Quarter 3 keywords
        q3_keywords = [
            'force', 'motion', 'speed', 'velocity', 'acceleration', 'distance', 'time', 
            'graph', 'friction', 'gravity', 'balanced', 'unbalanced', 'newton', 'heat', 
            'temperature', 'conduction', 'convection', 'radiation', 'conductor', 'insulator',
            'energy', 'thermal', 'kinetic energy', 'potential energy'
        ]
        
        # Quarter 4 keywords
        q4_keywords = [
            'fault', 'earthquake', 'seismic', 'epicenter', 'focus', 'magnitude', 'intensity', 
            'tsunami', 'volcano', 'weather', 'climate', 'monsoon', 'habagat', 'amihan', 
            'typhoon', 'storm', 'atmosphere', 'pressure', 'wind', 'humidity', 'cloud', 
            'disaster', 'risk', 'preparedness', 'evacuation', 'hazard', 'paghahanda',
            'early warning', 'drill', 'emergency'
        ]
        
        # Count matches with weights
        q1_score = 0
        q2_score = 0
        q3_score = 0
        q4_score = 0
        
        # Score each quarter with weighted keywords
        for kw in q1_keywords:
            if kw in text_lower:
                q1_score += 2 if len(kw.split()) > 1 else 1
                
        for kw in q2_keywords:
            if kw in text_lower:
                q2_score += 2 if len(kw.split()) > 1 else 1
                
        for kw in q3_keywords:
            if kw in text_lower:
                q3_score += 2 if len(kw.split()) > 1 else 1
                
        for kw in q4_keywords:
            if kw in text_lower:
                q4_score += 2 if len(kw.split()) > 1 else 1
        
        scores = [
            (q1_score, 'First Quarter'),
            (q2_score, 'Second Quarter'),
            (q3_score, 'Third Quarter'),
            (q4_score, 'Fourth Quarter')
        ]
        
        # Get the quarter with highest score
        max_score = max(scores, key=lambda x: x[0])
        
        # Only return if we have a meaningful score (at least 3 keyword matches)
        if max_score[0] >= 3:
            return max_score[1]
        
        # If no clear quarter, check for specific Filipino terms that indicate quarter
        if 'unang markahan' in text_lower or 'first quarter' in text_lower:
            return 'First Quarter'
        elif 'ikalawang markahan' in text_lower or 'second quarter' in text_lower:
            return 'Second Quarter'
        elif 'ikatlong markahan' in text_lower or 'third quarter' in text_lower:
            return 'Third Quarter'
        elif 'ikaapat na markahan' in text_lower or 'fourth quarter' in text_lower:
            return 'Fourth Quarter'
        
        return 'First Quarter'  # Default to First Quarter if can't determine
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity"""
        t1 = text1.lower().strip()
        t2 = text2.lower().strip()
        return SequenceMatcher(None, t1, t2).ratio()
    
    def find_matching_questions(self, lesson_text: str, num_questions: int = 5, 
                               topic_filter: str = None, quarter_filter: str = None,
                               exclude_questions: List[Dict] = None) -> List[Dict[str, Any]]:
        """Find questions matching lesson content, excluding specified questions
        
        This method tries to find questions with the specified topic and quarter.
        If not enough questions are available (after exclusions), it relaxes constraints
        to ensure variety and prevent repetition during refreshes.
        """
        
        if exclude_questions is None:
            exclude_questions = []
        
        # Extract topics
        topics = self.extract_topics_from_lesson(lesson_text)
        
        if not topics and not topic_filter:
            # Return random questions from the specified quarter if available
            return self._get_random_questions(num_questions, quarter_filter, exclude_questions)
        
        # Get dominant topic
        if topic_filter:
            dominant_topic = topic_filter
        else:
            dominant_topic = list(topics.keys())[0]
        
        # Helper function to check if question is excluded
        def is_question_excluded(q):
            question_text = q.get('question', '').lower()
            for excluded_q in exclude_questions:
                if (excluded_q.get('question', '').lower() == question_text or 
                    (excluded_q.get('question', '') and q.get('question', '') and 
                     self.calculate_similarity(excluded_q.get('question', ''), question_text) > 0.85)):
                    return True
            return False
        
        # PASS 1: Try strict topic + quarter matching
        scored_questions = []
        lesson_lower = lesson_text.lower()
        
        for i, q in enumerate(self.all_questions):
            if is_question_excluded(q):
                continue
            
            question_text = q.get('question', '').lower()
            topic = q.get('topic', '')
            quarter = q.get('quarter', '')
            
            # Strict: must match topic
            if dominant_topic.lower() not in topic.lower():
                continue
            
            # Higher score if topic matches
            score = 10
            
            # Bonus if quarter matches detected quarter
            if quarter_filter and quarter_filter in quarter:
                score += 5
            
            # Check for keyword matches
            for word in lesson_lower.split():
                if len(word) > 3 and word in question_text:
                    score += 1
            
            similarity = self.calculate_similarity(lesson_text, question_text)
            scored_questions.append((score + similarity, q, i))
        
        # Sort by score
        scored_questions.sort(reverse=True, key=lambda x: x[0])
        
        # If we have enough questions with strict topic matching, use them
        if len(scored_questions) >= num_questions:
            selected = scored_questions[:num_questions]
        else:
            # PASS 2: Fallback - allow all quarters but keep same topic
            selected_indices = set(idx for _, _, idx in scored_questions)
            fallback_questions = []
            
            for i, q in enumerate(self.all_questions):
                if i in selected_indices or is_question_excluded(q):
                    continue
                
                topic = q.get('topic', '')
                
                # Allow same topic but different quarter
                if dominant_topic.lower() in topic.lower():
                    question_text = q.get('question', '').lower()
                    score = 8  # Slightly lower than quarter-matched
                    
                    for word in lesson_lower.split():
                        if len(word) > 3 and word in question_text:
                            score += 1
                    
                    similarity = self.calculate_similarity(lesson_text, question_text)
                    fallback_questions.append((score + similarity, q, i))
            
            # Combine strict + fallback
            fallback_questions.sort(reverse=True, key=lambda x: x[0])
            needed = num_questions - len(scored_questions)
            scored_questions.extend(fallback_questions[:needed])
            selected = scored_questions[:num_questions]
            
            # PASS 3: If still not enough, fall back to random questions from the quarter
            if len(selected) < num_questions:
                # Get additional random questions from the detected quarter
                random_questions = self._get_random_questions(
                    num_questions - len(selected),
                    quarter_filter=quarter_filter,
                    exclude_questions=exclude_questions
                )
                
                # Convert random_questions (already formatted) back to selected format
                # But actually, we need to just use them directly since they're already formatted
                # So let's handle this differently
                if random_questions:
                    # We already have some selected questions, just append the random ones
                    return selected + random_questions if selected else random_questions
        
        # Build quiz items
        quiz = []
        for score, q, idx in selected:
            quiz_item = {
                'question': q['question'],
                'correct_answer': q.get('correct_index', 0),
                'choices': q.get('choices', []),
                'topic': q.get('topic', ''),
                'quarter': q.get('quarter', ''),
                'grade': self._get_grade_from_index(idx)
            }
            
            # Shuffle choices
            choices = quiz_item['choices'][:]
            correct = q['choices'][q.get('correct_index', 0)]
            random.shuffle(choices)
            quiz_item['correct_answer'] = choices.index(correct)
            quiz_item['choices'] = choices
            
            quiz.append(quiz_item)
        
        random.shuffle(quiz)
        return quiz
    
    def _get_random_questions(self, num_questions: int, quarter_filter: str = None, 
                             exclude_questions: List[Dict] = None) -> List[Dict[str, Any]]:
        """Get random questions from dataset, optionally filtered by quarter and excluding specified questions"""
        if exclude_questions is None:
            exclude_questions = []
        
        # Build list of questions to exclude by matching
        excluded_indices = set()
        for excluded_q in exclude_questions:
            excluded_text = excluded_q.get('question', '').lower()
            for i, q in enumerate(self.all_questions):
                if (q.get('question', '').lower() == excluded_text or
                    (excluded_text and q.get('question', '') and
                     self.calculate_similarity(excluded_text, q.get('question', '').lower()) > 0.85)):
                    excluded_indices.add(i)
        
        if quarter_filter:
            # Filter questions by quarter and exclude used ones
            available_questions = [q for i, q in enumerate(self.all_questions) 
                                  if q.get('quarter', '') == quarter_filter and i not in excluded_indices]
            if available_questions:
                selected = random.sample(available_questions, 
                                       min(num_questions, len(available_questions)))
            else:
                # If no available questions in quarter, get from all questions excluding used
                available_all = [q for i, q in enumerate(self.all_questions) if i not in excluded_indices]
                selected = random.sample(available_all, 
                                       min(num_questions, len(available_all)))
        else:
            available_questions = [q for i, q in enumerate(self.all_questions) if i not in excluded_indices]
            selected = random.sample(available_questions, 
                                   min(num_questions, len(available_questions)))
        
        quiz = []
        for q in selected:
            quiz_item = {
                'question': q['question'],
                'correct_answer': q.get('correct_index', 0),
                'choices': q.get('choices', []),
                'topic': q.get('topic', ''),
                'quarter': q.get('quarter', ''),
                'grade': 7
            }
            
            # Shuffle choices
            choices = quiz_item['choices'][:]
            correct = q['choices'][q.get('correct_index', 0)]
            random.shuffle(choices)
            quiz_item['correct_answer'] = choices.index(correct)
            quiz_item['choices'] = choices
            
            quiz.append(quiz_item)
        
        return quiz
    
    def validate_lesson_plan(self, lesson_text: str) -> Tuple[bool, str]:
        """
        Validate if the uploaded content appears to be an actual lesson plan
        Returns: (is_valid, error_message)
        Strict validation to prevent random files from being processed
        """
        if not lesson_text:
            return False, "No content found in the document."
        
        text_lower = lesson_text.lower()
        word_count = len(lesson_text.split())
        char_count = len(lesson_text.strip())
        
        # STRICT: Minimum content requirements
        if char_count < 500:
            return False, "Document is too short. Upload a detailed lesson plan with at least 500 characters."
        
        if word_count < 80:
            return False, "Document doesn't have enough content. Upload a proper lesson plan (minimum 80 words)."
        
        # STRICT: Reject resume/CV documents
        resume_keywords = {
            'resume', 'cv', 'curriculum vitae', 'email:', 'phone:', 'contact:',
            'address:', 'linkedin', 'github', 'professional experience', 'employment history',
            'objective:', 'summary:', 'technical skills:', 'education:', 'references:',
            'work experience', 'career objective', 'qualifications', 'accomplishments'
        }
        resume_count = sum(1 for keyword in resume_keywords if keyword in text_lower)
        if resume_count >= 2:
            return False, "This appears to be a resume or CV. Please upload a science lesson plan instead."
        
        # STRICT: Reject business/legal documents
        non_edu_keywords = {
            'invoice', 'receipt', 'purchase order', 'bill of lading', 'shipping',
            'product listing', 'menu', 'advertisement', 'contract', 'agreement',
            'legal notice', 'privacy policy', 'terms of service', 'pricing', 'quote',
            'payment', 'sale', 'transaction', 'business license', 'tax', 'order form'
        }
        non_edu_count = sum(1 for keyword in non_edu_keywords if keyword in text_lower)
        if non_edu_count >= 2:
            return False, "This is a business/legal document. Please upload a science lesson plan."
        
        # STRICT: Check for science curriculum topics
        topics = self.extract_topics_from_lesson(lesson_text)
        
        if not topics or len(topics) == 0:
            return False, "No science curriculum topics detected. This doesn't appear to be a science lesson plan."
        
        # STRICT: Require at least 1 strong topic (>8%) OR multiple topics (>5% each)
        strong_topics = [t for t in topics.values() if t.get('percentage', 0) >= 8]
        medium_topics = [t for t in topics.values() if t.get('percentage', 0) >= 5]
        
        if not strong_topics and len(medium_topics) < 2:
            return False, "This content doesn't adequately cover science curriculum topics. Please upload a focused science lesson."
        
        # STRICT: Look for educational content markers
        edu_markers = [
            'objective', 'learning outcomes', 'learning competency', 'lesson plan', 'grade level',
            'instruction', 'activity', 'discussion', 'assessment', 'learning materials', 'resources',
            'competency', 'standards', 'expectations', 'procedure', 'methodology', 'teaching',
            'students will', 'learners will', 'pupils will', 'classroom', 'practice', 'exercise',
            'worksheet', 'rubric', 'checklist', 'evaluation', 'quiz', 'test'
        ]
        edu_marker_count = sum(1 for marker in edu_markers if marker in text_lower)
        
        # If very few educational markers and document is generic, reject it
        if edu_marker_count < 2 and word_count < 200:
            return False, "This doesn't appear to be a properly structured lesson plan. Include learning objectives, activities, and assessments."
        
        # STRICT: Reject if it's mostly just a list of unrelated words/topics
        lines = lesson_text.split('\n')
        if len(lines) > 30:  # Many short lines suggest it might be a list
            short_lines = [l for l in lines if len(l.strip()) < 10 and l.strip()]
            if len(short_lines) / len(lines) > 0.5:  # More than 50% short lines
                return False, "Document appears to be a list rather than a coherent lesson plan."
        
        # All validations passed
        return True, ""
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get dataset statistics"""
        quarter_counts = {}
        topic_counts = {}
        grade_counts = {'7': len(self.grade7_questions), '8': len(self.grade8_questions)}
        
        for i, q in enumerate(self.all_questions):
            quarter = q.get('quarter', 'Unknown')
            topic = q.get('topic', 'General')
            
            quarter_counts[quarter] = quarter_counts.get(quarter, 0) + 1
            
            if quarter not in topic_counts:
                topic_counts[quarter] = {}
            topic_counts[quarter][topic] = topic_counts[quarter].get(topic, 0) + 1
        
        return {
            'total_questions': len(self.all_questions),
            'by_quarter': quarter_counts,
            'by_grade': grade_counts,
            'topics_by_quarter': topic_counts
        }