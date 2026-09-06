import { BookOpenText, FileSearch, MessageSquare, ShieldCheck } from 'lucide-react'

export default function AboutView() {
  return (
    <div className="about-view">
      <div className="about-card">
        <BookOpenText size={28} aria-hidden="true" className="about-card__icon" />
        <h2 className="about-card__title">About AI Knowledge Assistant</h2>
        <p className="about-card__text">
          AI Knowledge Assistant is a Retrieval-Augmented Generation (RAG) chatbot. It answers
          questions using only the content of the documents in the selected knowledge base:
          either the pre-loaded demo documents, or documents you upload yourself.
        </p>
        <ul className="about-card__points">
          <li>
            <MessageSquare size={18} aria-hidden="true" />
            <span>Ask questions in plain language and get answers grounded in your documents.</span>
          </li>
          <li>
            <FileSearch size={18} aria-hidden="true" />
            <span>Every answer cites the source documents it was drawn from.</span>
          </li>
          <li>
            <ShieldCheck size={18} aria-hidden="true" />
            <span>Demo and personal document sets stay completely separate.</span>
          </li>
        </ul>
      </div>
    </div>
  )
}
