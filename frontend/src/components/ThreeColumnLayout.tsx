import React, { useState, useEffect } from 'react';
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
  const [leftWidth, setLeftWidth] = useState(360);
  const [rightWidth, setRightWidth] = useState(450);
  const [resizingPanel, setResizingPanel] = useState<'left' | 'right' | null>(null);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!resizingPanel) return;

      if (resizingPanel === 'left') {
        const newWidth = e.clientX;
        if (newWidth >= 280 && newWidth <= 620) {
          setLeftWidth(newWidth);
        }
        return;
      }

      if (resizingPanel === 'right') {
        const newWidth = window.innerWidth - e.clientX;
        if (newWidth >= 300 && newWidth <= 800) {
          setRightWidth(newWidth);
        }
      }
    };

    const handleMouseUp = () => {
      setResizingPanel(null);
    };

    if (resizingPanel) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [resizingPanel]);

  return (
    <div className="flex h-full relative">
      {/* LEFT SIDEBAR */}
      <div 
        className={`
          ${resizingPanel === 'left' ? 'transition-none' : 'transition-all duration-300 ease-in-out'}
          ${leftCollapsed ? 'w-0' : ''}
          border-r border-gray-200 
          overflow-hidden
          bg-white
          flex-shrink-0
          relative
        `}
        style={!leftCollapsed ? { width: `${leftWidth}px` } : {}}
      >
        {!leftCollapsed && (
          <>
          {/* Resize handle */}
          <div
            onMouseDown={() => setResizingPanel('left')}
            className={`
              absolute right-0 top-0 bottom-0 w-1 cursor-col-resize
              hover:bg-blue-500 transition-colors z-10
              ${resizingPanel === 'left' ? 'bg-blue-500' : 'bg-transparent'}
            `}
            title={t('layout.resize')}
          />

          <div className="h-full flex flex-col" style={{ width: `${leftWidth}px` }}>
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
            <div className="flex-1 overflow-hidden">
              {leftSidebar}
            </div>
          </div>
          </>
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
              onMouseDown={() => setResizingPanel('right')}
              className={`
                absolute left-0 top-0 bottom-0 w-1 cursor-col-resize
                hover:bg-blue-500 transition-colors z-10
                ${resizingPanel === 'right' ? 'bg-blue-500' : 'bg-transparent'}
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
