import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

interface ThreeColumnLayoutProps {
  leftSidebar: React.ReactNode;
  centerPanel: React.ReactNode;
  rightSidebar: React.ReactNode;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  onToggleLeft: () => void;
  onToggleRight: () => void;
}

const ThreeColumnLayout: React.FC<ThreeColumnLayoutProps> = ({
  leftSidebar,
  centerPanel,
  rightSidebar,
  leftCollapsed,
  rightCollapsed,
  onToggleLeft,
  onToggleRight,
}) => {
  const { t } = useTranslation();
  const [rightWidth, setRightWidth] = useState(450);
  const [isResizing, setIsResizing] = useState(false);
  const resizeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      
      const newWidth = window.innerWidth - e.clientX;
      if (newWidth >= 300 && newWidth <= 800) {
        setRightWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  return (
    <div className="flex h-full relative">
      {/* LEFT SIDEBAR */}
      <div 
        className={`
          transition-all duration-300 ease-in-out
          ${leftCollapsed ? 'w-0' : 'w-[280px]'}
          border-r border-gray-200 
          overflow-hidden
          bg-white
          flex-shrink-0
        `}
      >
        {!leftCollapsed && (
          <div className="w-[280px] h-full flex flex-col">
            {/* Sidebar header with toggle - NO BORDER */}
            <div className="flex items-center justify-end px-2 py-2">
              <button
                onClick={onToggleLeft}
                className="
                  bg-gray-100 border border-gray-300 rounded
                  w-7 h-7 flex items-center justify-center
                  hover:bg-gray-200 shadow-sm
                "
                title={t('layout.hideLeft')}
              >
                <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
            </div>

            {/* Sidebar content */}
            <div className="flex-1 overflow-y-auto">
              {leftSidebar}
            </div>
          </div>
        )}
      </div>
      
      {/* Left expand button */}
      {leftCollapsed && (
        <button
          onClick={onToggleLeft}
          className="
            fixed left-0 top-20 z-50
            bg-gray-100 border border-gray-300 border-l-0 rounded-r
            px-1.5 py-3 hover:bg-gray-200 shadow-sm
          "
          title={t('layout.showLeft')}
        >
          <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      )}
      
      {/* CENTER PANEL */}
      <div className="flex-1 overflow-y-auto bg-gray-50">
        <div className="max-w-5xl mx-auto">
          {centerPanel}
        </div>
      </div>
      
      {/* RIGHT SIDEBAR - RESIZABLE */}
      <div 
        className={`
          transition-none
          ${rightCollapsed ? 'w-0' : ''}
          border-l border-gray-200 
          overflow-hidden
          bg-white
          flex-shrink-0
          relative
        `}
        style={!rightCollapsed ? { width: `${rightWidth}px` } : {}}
      >
        {!rightCollapsed && (
          <>
            {/* Resize handle */}
            <div
              ref={resizeRef}
              onMouseDown={() => setIsResizing(true)}
              className={`
                absolute left-0 top-0 bottom-0 w-1 cursor-col-resize
                hover:bg-blue-500 transition-colors z-10
                ${isResizing ? 'bg-blue-500' : 'bg-transparent'}
              `}
              title={t('layout.resize')}
            />

            <div className="h-full flex flex-col" style={{ width: `${rightWidth}px` }}>
              {/* Sidebar header with toggle - NO BORDER */}
              <div className="flex items-center justify-start px-2 py-2">
                <button
                  onClick={onToggleRight}
                  className="
                    bg-gray-100 border border-gray-300 rounded
                    w-7 h-7 flex items-center justify-center
                    hover:bg-gray-200 shadow-sm
                  "
                  title={t('layout.hideRight')}
                >
                  <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>

              {/* Sidebar content */}
              <div className="flex-1 overflow-hidden">
                {rightSidebar}
              </div>
            </div>
          </>
        )}
      </div>
      
      {/* Right expand button */}
      {rightCollapsed && (
        <button
          onClick={onToggleRight}
          className="
            fixed right-0 top-20 z-50
            bg-gray-100 border border-gray-300 border-r-0 rounded-l
            px-1.5 py-3 hover:bg-gray-200 shadow-sm
          "
          title={t('layout.showRight')}
        >
          <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      )}
    </div>
  );
};

export default ThreeColumnLayout;
